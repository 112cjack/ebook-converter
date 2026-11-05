# -*- coding: utf-8 -*-
"""任务队列与后台 worker。

每个上传文件对应一个上传记录；每次提交转换为其创建一个任务，
任务在内存字典中保存（即本次运行期间的转换历史，程序重启后清空）。
监听自动转换按源文件路径直接建任务（upload_id 为 None），不复制进上传目录。
单 worker 线程从 FIFO 队列逐个取任务，以子进程调用引擎层
ebook_converter.convert_file，本模块只做调度、重名判定与状态管理。
"""

import logging
import queue
import threading
import time
import uuid
from pathlib import Path

import ebook_converter as ec

log = logging.getLogger("ebook-converter")

# 任务状态机：queued -> converting -> done / failed / skipped / cancelled
QUEUED = "queued"
CONVERTING = "converting"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"
CANCELLED = "cancelled"

STATUS_LABEL = {
    QUEUED: "排队中",
    CONVERTING: "转换中",
    DONE: "已完成",
    FAILED: "失败",
    SKIPPED: "已跳过",
    CANCELLED: "已取消",
}

# 引擎层与系统层错误 -> 通俗文案（引擎原始报错保留在 error_detail 供排查）
FRIENDLY_ERROR = "文件可能已损坏或受版权保护（DRM），暂不支持转换"


# 主名截断阈值：保证 tmp 路径 + 输出路径不超出 Windows MAX_PATH（260 字符）
MAX_FILENAME_STEM = 80


def safe_filename(name):
    """清洗上传文件名：去路径成分与 Windows 非法字符，超长主名截断，保留中文与扩展名。

    返回 (清洗后的名字, 是否发生了截断)。
    """
    name = Path(str(name).replace("\\", "/")).name
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    cleaned = cleaned.strip() or "未命名"
    stem, dot, ext = cleaned.rpartition(".")
    if dot and 0 < len(ext) <= 10:
        if len(stem) > MAX_FILENAME_STEM:
            return stem[:MAX_FILENAME_STEM] + dot + ext, True
    elif len(cleaned) > MAX_FILENAME_STEM:
        return cleaned[:MAX_FILENAME_STEM], True
    return cleaned, False


def path_under_roots(path, roots):
    """判断 path 是否落在任一 root 目录之下（含 root 自身文件）。"""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


class TaskManager:
    """上传记录、转换任务与串行 worker 的唯一持有者。"""

    def __init__(self, upload_dir, engine_resolver=None):
        self.upload_dir = Path(upload_dir)
        self.uploads = {}       # upload_id -> 上传记录
        self.tasks = {}         # task_id -> 任务记录
        self.upload_order = []  # 保持列表展示顺序
        self.task_order = []
        self.registered_dirs = set()  # open-folder 只接受这里登记过的目录
        self.registered_files = set()  # open-file 只接受这里登记过的输出文件
        self._queue = queue.Queue()
        self._seen_dst = {}     # 运行期内 dst -> 来源文件名，用于重名提示
        self._cancel_requests = set()  # 请求取消的任务 id（worker 通过 cancel_check 轮询）
        self._lock = threading.Lock()
        self.resolve_engine = engine_resolver or (lambda: ec.find_engine())
        worker = threading.Thread(target=self._work_loop, daemon=True, name="convert-worker")
        worker.start()
        self._worker = worker

    # ── 上传 ──

    def store_upload(self, filename, data):
        """保存上传文件到工作目录，返回上传记录。调用方已做扩展名白名单校验。"""
        ext = Path(filename).suffix.lower()
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name, truncated = safe_filename(filename)
        stored = uuid.uuid4().hex[:8] + "_" + safe_name
        stored_path = self.upload_dir / stored
        stored_path.write_bytes(data)
        record = {
            "id": uuid.uuid4().hex[:12],
            "name": safe_name,
            "stored_name": stored,
            "size": len(data),
            "format": ext.lstrip("."),
            "removed": False,
            "truncated": truncated,
            "scanned_pdf": ext == ".pdf" and ec.pdf_has_text_layer(stored_path) is False,
        }
        with self._lock:
            self.uploads[record["id"]] = record
            self.upload_order.append(record["id"])
        self.registered_dirs.add(str(self.upload_dir))
        return record

    def removable_upload_ids(self):
        """可移除的上传：未被移除、且没有转换中的任务（排队中的允许移除）。"""
        busy = {
            t["upload_id"]
            for t in self.tasks.values()
            if t["status"] == CONVERTING and t.get("upload_id")
        }
        with self._lock:
            return [
                uid for uid in self.upload_order
                if not self.uploads[uid]["removed"] and uid not in busy
            ]

    def remove_uploads(self, upload_ids):
        """把上传标记为已移除（列表不再显示），删除临时文件；任务记录保留为历史。"""
        with self._lock:
            for uid in upload_ids:
                record = self.uploads.get(uid)
                if record is None or record["removed"]:
                    continue
                record["removed"] = True
                # 若还有排队任务（并发窗口内），置为跳过，worker 不会再执行
                for task in self.tasks.values():
                    if task["upload_id"] == uid and task["status"] == QUEUED:
                        task["status"] = SKIPPED
                        task["message"] = "已从列表移除"
            removed = [self.uploads[uid] for uid in upload_ids if uid in self.uploads]
        for record in removed:
            (self.upload_dir / record["stored_name"]).unlink(missing_ok=True)

    def upload_path(self, record):
        return self.upload_dir / record["stored_name"]

    # ── 任务创建 ──

    def create_tasks(self, upload_ids, target_format, output_dir, overwrite=False, preset="default"):
        """为一组上传创建转换任务并入队，返回任务列表。

        target_format 必须在引擎层 OUTPUT_FORMATS 内；engine 未就绪时抛 EngineNotFoundError。
        overwrite 为 True 时转换前删除已存在的同名输出（覆盖重转）；
        preset 为引擎层 CONVERSION_PRESETS 的键（阅读设备优化）；
        源格式与目标格式相同的文件直接建 skipped 任务，不入队。
        """
        if target_format not in ec.OUTPUT_FORMATS:
            raise ValueError(f"不支持的输出格式: {target_format}")
        if preset not in ec.CONVERSION_PRESETS:
            raise ValueError(f"未知的转换预设: {preset}")
        engine = self.resolve_engine()
        if engine is None:
            raise ec.EngineNotFoundError("未检测到 Calibre，请先安装或在设置中指定路径")

        out_dir = Path(output_dir)
        created = []
        with self._lock:
            for uid in upload_ids:
                record = self.uploads.get(uid)
                if record is None or record["removed"]:
                    continue
                now = time.time()
                task = {
                    "id": uuid.uuid4().hex[:12],
                    "upload_id": uid,
                    "name": record["name"],
                    "src_path": str(self.upload_path(record)),
                    "format_in": record["format"],
                    "format_out": target_format,
                    "status": QUEUED,
                    "progress": 0,
                    "message": None,
                    "error": None,
                    "error_detail": None,
                    "output_path": str(out_dir / (Path(record["name"]).stem + "." + target_format)),
                    "output_dir": str(out_dir),
                    "overwrite": overwrite,
                    "preset": preset,
                    "created_at": now,
                    "started_at": None,
                    "finished_at": None,
                }
                if record["format"] == target_format:
                    # 同格式转换对用户没有意义，直接标记跳过（设计文档 4 / C1）
                    task["status"] = SKIPPED
                    task["message"] = f"源文件已是 {target_format} 格式，无需转换"
                    task["finished_at"] = now
                self.tasks[task["id"]] = task
                self.task_order.append(task["id"])
                created.append(task)
                if task["status"] == QUEUED:
                    self._queue.put(task["id"])
        if created:
            log.info("创建 %d 个转换任务（目标 %s -> %s，覆盖=%s）",
                     len(created), "多文件" if len(created) > 1 else created[0]["name"],
                     target_format, overwrite)
        return created

    def create_path_tasks(self, paths, target_format, output_dir, allowed_roots,
                          overwrite=False, preset="default"):
        """为监听目录里的源文件按绝对路径创建转换任务（不复制进上传目录）。

        allowed_roots 之外的路径只建 failed 任务并说明原因，不入队、不调用转换；
        源格式与目标格式相同的文件直接建 skipped 任务；返回创建的任务列表。
        """
        if target_format not in ec.OUTPUT_FORMATS:
            raise ValueError(f"不支持的输出格式: {target_format}")
        if preset not in ec.CONVERSION_PRESETS:
            raise ValueError(f"未知的转换预设: {preset}")
        engine = self.resolve_engine()
        if engine is None:
            raise ec.EngineNotFoundError("未检测到 Calibre，请先安装或在设置中指定路径")

        out_dir = Path(output_dir)
        created = []
        with self._lock:
            for raw in paths:
                src = Path(raw)
                now = time.time()
                name = src.name
                fmt_in = src.suffix.lower().lstrip(".")
                task = {
                    "id": uuid.uuid4().hex[:12],
                    "upload_id": None,
                    "name": name,
                    "src_path": str(src.resolve()) if src.exists() else str(src),
                    "format_in": fmt_in,
                    "format_out": target_format,
                    "status": QUEUED,
                    "progress": 0,
                    "message": None,
                    "error": None,
                    "error_detail": None,
                    "output_path": str(out_dir / (src.stem + "." + target_format)),
                    "output_dir": str(out_dir),
                    "overwrite": overwrite,
                    "preset": preset,
                    "created_at": now,
                    "started_at": None,
                    "finished_at": None,
                }
                if not path_under_roots(src, allowed_roots):
                    task["status"] = FAILED
                    task["error"] = "源文件不在监听目录内"
                    task["finished_at"] = now
                elif fmt_in == target_format:
                    task["status"] = SKIPPED
                    task["message"] = f"源文件已是 {target_format} 格式，无需转换"
                    task["finished_at"] = now
                self.tasks[task["id"]] = task
                self.task_order.append(task["id"])
                created.append(task)
                if task["status"] == QUEUED:
                    self._queue.put(task["id"])
        if created:
            log.info("按路径创建 %d 个转换任务（目标 %s）", len(created), target_format)
        return created

    def request_cancel(self, task_id):
        """请求取消一个转换中的任务；成功返回 True。"""
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None or task["status"] != CONVERTING:
                return False
            self._cancel_requests.add(task_id)
            log.info("请求取消任务：%s", task["name"])
            return True

    # ── worker ──

    def _work_loop(self):
        while True:
            task_id = self._queue.get()
            try:
                self._run_task(task_id)
            except Exception as exc:  # worker 线程绝不退出，内部错误落到任务上
                self._finish(task_id, FAILED, error=f"内部错误: {exc}")
            finally:
                self._queue.task_done()

    def _run_task(self, task_id):
        task = self.tasks.get(task_id)
        if task is None or task["status"] != QUEUED:
            return
        task["status"] = CONVERTING
        task["started_at"] = time.time()

        dst = Path(task["output_path"])
        prior = self._seen_dst.get(dst)
        if prior is not None and prior != task["name"]:
            self._finish(task_id, SKIPPED, message=f"输出与 {prior} 重名")
            return
        self._seen_dst[dst] = task["name"]
        if task.get("overwrite") and dst.exists():
            dst.unlink(missing_ok=True)  # 覆盖重转：清掉旧输出再转

        warning = ""
        if task["format_in"] == "pdf" and task["format_out"] != "pdf":
            if ec.pdf_has_text_layer(task["src_path"]) is False:
                warning = ec.SCANNED_PDF_WARNING

        engine = self.resolve_engine()
        if engine is None:
            self._finish(task_id, FAILED, error="未检测到 Calibre，请先安装或在设置中指定路径")
            return

        def on_progress(pct):
            task["progress"] = max(0, min(100, int(pct)))

        cancel_check = lambda: task_id in self._cancel_requests  # noqa: E731 - 闭包捕获 task_id
        options = ec.CONVERSION_PRESETS.get(task.get("preset") or "default")

        try:
            status, message = ec.convert_file(engine, task["src_path"], dst,
                                              on_progress=on_progress,
                                              cancel_check=cancel_check,
                                              options=options)
        except OSError as exc:
            self._finish(task_id, FAILED, error=f"无法启动转换引擎: {exc}")
            return

        if status == ec.STATUS_OK:
            task["output_path"] = str(dst)
            try:
                self.registered_files.add(str(dst.resolve()))
            except OSError:
                self.registered_files.add(str(dst))
            self._finish(task_id, DONE, message=f"{message}；{warning}" if warning else message)
        elif status == ec.STATUS_SKIPPED:
            self._finish(task_id, SKIPPED, message=message)
        elif message == "已取消":
            self._finish(task_id, CANCELLED, message=message)
        else:
            # 引擎报错尾巴映射为通俗文案，原始信息保留在 error_detail（技术方案 5.3）
            detail = self._engine_error_detail(message)
            self._finish(
                task_id, FAILED,
                error=FRIENDLY_ERROR if detail else message,
                error_detail=detail,
            )

    @staticmethod
    def _engine_error_detail(message):
        """引擎失败消息的尾巴（不含输出大小校验等已通俗的提示）。"""
        if not message:
            return None
        return message

    def _finish(self, task_id, status, message=None, error=None, error_detail=None):
        task = self.tasks.get(task_id)
        if task is None:
            return
        task["status"] = status
        task["message"] = message
        task["error"] = error
        task["error_detail"] = error_detail
        task["finished_at"] = time.time()
        log.info("任务结束 [%s] %s：%s", STATUS_LABEL[status], task["name"],
                 message or error or "")

    # ── 查询与同步 ──

    def wait_idle(self, timeout=30):
        """等待全部任务离开队列并完成（测试用）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if (self._queue.unfinished_tasks == 0
                    and all(t["status"] not in (QUEUED, CONVERTING) for t in self.tasks.values())):
                return True
            time.sleep(0.02)
        return False

    def latest_task_of(self, upload_id):
        """某个上传最新的一次转换任务（列表行展示用）。"""
        result = None
        for tid in self.task_order:
            task = self.tasks[tid]
            if task["upload_id"] == upload_id:
                result = task
        return result

    def snapshot(self):
        """返回 uploads 与 tasks 的只读视图（按创建顺序）。"""
        with self._lock:
            uploads = [dict(self.uploads[uid]) for uid in self.upload_order if uid in self.uploads]
            tasks = [dict(self.tasks[tid]) for tid in self.task_order if tid in self.tasks]
        return uploads, tasks
