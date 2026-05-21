import json
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from dotenv import load_dotenv

from fb_group_poster import (
    AUDIENCE_DEFAULT,
    AUDIENCE_FRIENDS,
    AUDIENCE_ONLY_ME,
    AUDIENCE_PUBLIC,
    PostTask,
    RunnerConfig,
    normalize_audience,
    parse_datetime,
    run_tasks,
)

try:
    import windnd  # type: ignore
except Exception:
    windnd = None


WW_GROUP_PRESET = [
    "https://www.facebook.com/groups/wutheringwaves.vi",
    "https://www.facebook.com/groups/wutheringwaves",
    "https://www.facebook.com/groups/wutheringwaves.muaban.game",
    "https://www.facebook.com/groups/wutheringwavesvietnamofficial",
]
PERSONAL_PROFILE_URL = "https://www.facebook.com/me"

AUDIENCE_OPTIONS = [
    ("Mặc định", AUDIENCE_DEFAULT),
    ("Công khai", AUDIENCE_PUBLIC),
    ("Bạn bè", AUDIENCE_FRIENDS),
    ("Chỉ mình tôi", AUDIENCE_ONLY_ME),
]
AUDIENCE_LABEL_TO_VALUE = {label: value for label, value in AUDIENCE_OPTIONS}
AUDIENCE_VALUE_TO_LABEL = {value: label for label, value in AUDIENCE_OPTIONS}

MEDIA_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
}


def detect_coccoc_defaults() -> tuple[str, str]:
    exe_candidates = [
        r"C:\Program Files\CocCoc\Browser\Application\browser.exe",
        r"C:\Program Files (x86)\CocCoc\Browser\Application\browser.exe",
        str(Path.home() / "AppData/Local/CocCoc/Browser/Application/browser.exe"),
    ]
    exe_path = next((candidate for candidate in exe_candidates if Path(candidate).exists()), exe_candidates[0])
    user_data_dir = str(Path.home() / "AppData/Local/CocCoc/Browser/User Data")
    return exe_path, user_data_dir


def detect_coccoc_profiles(user_data_dir: Path) -> list[tuple[str, str]]:
    local_state_path = user_data_dir / "Local State"
    if not local_state_path.exists():
        return []

    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    info_cache = data.get("profile", {}).get("info_cache", {})
    if not isinstance(info_cache, dict):
        return []

    profiles: list[tuple[str, str]] = []
    for profile_dir, payload in info_cache.items():
        if not isinstance(profile_dir, str):
            continue

        name = ""
        if isinstance(payload, dict):
            name = str(payload.get("name") or "").strip()

        label = f"{name} ({profile_dir})" if name else profile_dir
        profiles.append((label, profile_dir))

    profiles.sort(key=lambda item: item[0].lower())
    return profiles


class FbPosterGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FB Group Video Poster - GUI")
        self.root.geometry("1320x860")

        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None

        self.task_store: dict[str, dict] = {}
        self.task_id_counter = 1
        self.coccoc_profile_map: dict[str, str] = {}
        self.editing_task_iid: str | None = None

        self._build_vars()
        self._build_ui()
        self._refresh_coccoc_profiles(initial=True)
        self._load_ww_groups(silent=True)
        self._register_drag_drop()

        self.root.after(150, self._drain_log_queue)

    def _build_vars(self) -> None:
        load_dotenv()

        default_exe, default_user_data = detect_coccoc_defaults()

        self.session_path_var = tk.StringVar(value=str(Path(".fb_session.json").resolve()))
        self.min_delay_var = tk.StringVar(value="20")
        self.max_delay_var = tk.StringVar(value="45")
        self.slow_mo_var = tk.StringVar(value="120")
        self.timeout_var = tk.StringVar(value="180000")
        self.locale_var = tk.StringVar(value="vi-VN")
        self.timezone_var = tk.StringVar(value="Asia/Ho_Chi_Minh")

        self.headless_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)

        self.use_coccoc_var = tk.BooleanVar(value=True)
        self.coccoc_exe_var = tk.StringVar(value=default_exe)
        self.coccoc_user_data_var = tk.StringVar(value=default_user_data)
        self.coccoc_profile_label_var = tk.StringVar(value="")

        self.group_url_var = tk.StringVar()
        self.video_path_var = tk.StringVar()
        self.schedule_at_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.schedule_step_minutes_var = tk.StringVar(value="10")
        self.audience_var = tk.StringVar(value=AUDIENCE_VALUE_TO_LABEL[AUDIENCE_DEFAULT])
        self.status_var = tk.StringVar(value="Sẵn sàng")

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        container.rowconfigure(3, weight=1)

        self._build_settings(container)
        self._build_main_area(container)
        self._build_run_area(container)
        self._build_log_area(container)

    def _build_settings(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Cấu hình chạy", padding=10)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        for col in range(8):
            frame.columnconfigure(col, weight=1 if col in {1, 3, 5} else 0)

        ttk.Label(frame, text="Session file").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.session_path_var).grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(frame, text="Chọn", command=self._choose_session_path).grid(row=0, column=2)

        ttk.Label(frame, text="Locale").grid(row=0, column=3, sticky="w", padx=(10, 0))
        ttk.Entry(frame, textvariable=self.locale_var, width=12).grid(row=0, column=4, sticky="w", padx=(6, 6))

        ttk.Label(frame, text="Timezone").grid(row=0, column=5, sticky="w")
        ttk.Entry(frame, textvariable=self.timezone_var, width=20).grid(row=0, column=6, sticky="w", padx=(6, 0))

        ttk.Label(frame, text="Delay min (s)").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.min_delay_var, width=10).grid(row=1, column=1, sticky="w", padx=(6, 6), pady=(10, 0))

        ttk.Label(frame, text="Delay max (s)").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.max_delay_var, width=10).grid(row=1, column=3, sticky="w", padx=(6, 6), pady=(10, 0))

        ttk.Label(frame, text="SlowMo (ms)").grid(row=1, column=4, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.slow_mo_var, width=10).grid(row=1, column=5, sticky="w", padx=(6, 6), pady=(10, 0))

        ttk.Label(frame, text="Post timeout (ms)").grid(row=1, column=6, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.timeout_var, width=12).grid(row=1, column=7, sticky="w", padx=(6, 0), pady=(10, 0))

        ttk.Checkbutton(frame, text="Headless", variable=self.headless_var).grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Checkbutton(frame, text="Dry Run", variable=self.dry_run_var).grid(row=2, column=1, sticky="w", pady=(10, 0))

        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=3, column=0, columnspan=8, sticky="ew", pady=(10, 8))

        ttk.Checkbutton(
            frame,
            text="Dùng Cốc Cốc profile thật",
            variable=self.use_coccoc_var,
        ).grid(row=4, column=0, sticky="w")

        ttk.Label(frame, text="Cốc Cốc exe").grid(row=4, column=2, sticky="w")
        ttk.Entry(frame, textvariable=self.coccoc_exe_var).grid(row=4, column=3, columnspan=3, sticky="ew", padx=(6, 6))
        ttk.Button(frame, text="Chọn", command=self._choose_coccoc_exe).grid(row=4, column=6, sticky="w")

        ttk.Label(frame, text="User Data").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.coccoc_user_data_var).grid(row=5, column=1, columnspan=4, sticky="ew", padx=(6, 6), pady=(8, 0))
        ttk.Button(frame, text="Chọn thư mục", command=self._choose_coccoc_user_data).grid(row=5, column=5, sticky="w", pady=(8, 0))

        ttk.Label(frame, text="Profile").grid(row=5, column=6, sticky="w", pady=(8, 0))
        self.profile_combo = ttk.Combobox(
            frame,
            textvariable=self.coccoc_profile_label_var,
            state="readonly",
            width=26,
        )
        self.profile_combo.grid(row=5, column=7, sticky="w", pady=(8, 0))

        action_row = ttk.Frame(frame)
        action_row.grid(row=6, column=0, columnspan=8, sticky="w", pady=(8, 0))
        ttk.Button(action_row, text="Quét profile", command=self._refresh_coccoc_profiles).pack(side=tk.LEFT)
        ttk.Button(action_row, text="Chọn nhanh A1", command=self._select_a1_profile).pack(side=tk.LEFT, padx=(6, 0))

    def _build_main_area(self, parent: ttk.Frame) -> None:
        main = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", pady=(0, 10))

        left = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=1)
        main.add(right, weight=2)

        self._build_groups_panel(left)
        self._build_tasks_panel(right)

    def _build_groups_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Danh sách đích đăng", padding=8)
        panel.pack(fill=tk.BOTH, expand=True)

        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        input_row = ttk.Frame(panel)
        input_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        input_row.columnconfigure(0, weight=1)

        ttk.Entry(input_row, textvariable=self.group_url_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(input_row, text="Thêm", command=self._add_group).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(input_row, text="Cập nhật nhóm chọn", command=self._update_selected_group_from_entry).grid(
            row=0, column=2, padx=(6, 0)
        )

        quick_row = ttk.Frame(panel)
        quick_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(quick_row, text="Nạp 4 nhóm WW", command=self._load_ww_groups).pack(side=tk.LEFT)
        ttk.Button(quick_row, text="Thêm trang cá nhân", command=self._add_personal_profile_target).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(quick_row, text="Chọn tất cả", command=self._select_all_groups).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(quick_row, text="Bỏ chọn", command=self._clear_group_selection).pack(side=tk.LEFT, padx=(6, 0))

        self.group_listbox = tk.Listbox(panel, selectmode=tk.EXTENDED)
        self.group_listbox.grid(row=2, column=0, sticky="nsew")
        self.group_listbox.bind("<<ListboxSelect>>", self._on_group_selected)

        scroll = ttk.Scrollbar(panel, orient=tk.VERTICAL, command=self.group_listbox.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.group_listbox.configure(yscrollcommand=scroll.set)

        btn_row = ttk.Frame(panel)
        btn_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        ttk.Button(btn_row, text="Mở nhóm", command=self._open_selected_group).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Xoá nhóm chọn", command=self._remove_selected_groups).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_row, text="Import TXT", command=self._import_groups_txt).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_row, text="Export TXT", command=self._export_groups_txt).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_row, text="Clear", command=self._clear_groups).pack(side=tk.LEFT, padx=(6, 0))

    def _build_tasks_panel(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        editor = ttk.LabelFrame(parent, text="Soạn bài", padding=8)
        editor.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        editor.columnconfigure(1, weight=1)

        ttk.Label(editor, text="Media").grid(row=0, column=0, sticky="w")
        ttk.Entry(editor, textvariable=self.video_path_var).grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(editor, text="Chọn file", command=self._choose_video_file).grid(row=0, column=2)
        ttk.Label(editor, text="(kéo-thả video/hình vào cửa sổ để nhận file)").grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )

        ttk.Label(editor, text="Giờ đăng").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(editor, textvariable=self.schedule_at_var).grid(row=1, column=1, sticky="w", padx=(6, 6), pady=(8, 0))

        schedule_btns = ttk.Frame(editor)
        schedule_btns.grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Button(schedule_btns, text="Now", command=lambda: self._set_schedule_after_minutes(0)).pack(side=tk.LEFT)
        ttk.Button(schedule_btns, text="+5m", command=lambda: self._set_schedule_after_minutes(5)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(schedule_btns, text="+15m", command=lambda: self._set_schedule_after_minutes(15)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(schedule_btns, text="+30m", command=lambda: self._set_schedule_after_minutes(30)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(schedule_btns, text="+60m", command=lambda: self._set_schedule_after_minutes(60)).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(editor, text="Quyền riêng tư").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.audience_combo = ttk.Combobox(
            editor,
            textvariable=self.audience_var,
            state="readonly",
            values=[label for label, _ in AUDIENCE_OPTIONS],
            width=16,
        )
        self.audience_combo.grid(row=2, column=1, sticky="w", padx=(6, 6), pady=(8, 0))

        step_row = ttk.Frame(editor)
        step_row.grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Label(step_row, text="Bước lịch (phút)").pack(side=tk.LEFT)
        ttk.Entry(step_row, textvariable=self.schedule_step_minutes_var, width=6).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(step_row, text="Xếp lịch theo nhóm chọn", command=self._queue_selected_groups_with_step).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(editor, text="(chỉ áp dụng cho đích trang cá nhân)").grid(row=2, column=3, sticky="w", pady=(8, 0))

        ttk.Label(editor, text="Caption").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        self.caption_text = tk.Text(editor, height=6, wrap=tk.WORD)
        self.caption_text.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(8, 0))

        button_row = ttk.Frame(editor)
        button_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        ttk.Button(button_row, text="Thêm nhóm chọn", command=self._add_task_for_selected_groups).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Thêm tất cả nhóm", command=self._add_task_for_all_groups).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_row, text="Nạp dòng chọn", command=self._load_selected_task_for_edit).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_row, text="Cập nhật dòng chọn", command=self._update_selected_task).pack(side=tk.LEFT, padx=(6, 0))

        queue_frame = ttk.LabelFrame(parent, text="Hàng đợi đăng", padding=8)
        queue_frame.grid(row=1, column=0, sticky="nsew")
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)

        columns = ("group_url", "video_path", "schedule_at", "audience", "status")
        self.task_tree = ttk.Treeview(queue_frame, columns=columns, show="headings", height=14)
        self.task_tree.heading("group_url", text="Group URL")
        self.task_tree.heading("video_path", text="Media")
        self.task_tree.heading("schedule_at", text="Giờ đăng")
        self.task_tree.heading("audience", text="Riêng tư")
        self.task_tree.heading("status", text="Trạng thái")

        self.task_tree.column("group_url", width=340, anchor=tk.W)
        self.task_tree.column("video_path", width=220, anchor=tk.W)
        self.task_tree.column("schedule_at", width=150, anchor=tk.W)
        self.task_tree.column("audience", width=110, anchor=tk.W)
        self.task_tree.column("status", width=120, anchor=tk.W)

        self.task_tree.grid(row=0, column=0, sticky="nsew")
        self.task_tree.bind("<Double-1>", self._load_selected_task_for_edit)

        y_scroll = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self.task_tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.task_tree.configure(yscrollcommand=y_scroll.set)

        x_scroll = ttk.Scrollbar(queue_frame, orient=tk.HORIZONTAL, command=self.task_tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.task_tree.configure(xscrollcommand=x_scroll.set)

        actions = ttk.Frame(queue_frame)
        actions.grid(row=2, column=0, sticky="w", pady=(8, 0))

        ttk.Button(actions, text="Áp dụng giờ cho dòng chọn", command=self._apply_schedule_to_selected_tasks).pack(side=tk.LEFT)
        ttk.Button(actions, text="Áp dụng giờ cho tất cả", command=self._apply_schedule_to_all_tasks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Áp dụng nhóm chọn", command=self._apply_selected_group_to_selected_tasks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Áp dụng media cho dòng chọn", command=self._apply_media_to_selected_tasks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Áp dụng riêng tư", command=self._apply_audience_to_selected_tasks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Xoá dòng chọn", command=self._remove_selected_tasks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Nhân đôi dòng", command=self._duplicate_selected_tasks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Clear queue", command=self._clear_tasks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Lưu plan", command=self._save_plan).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Mở plan", command=self._load_plan).pack(side=tk.LEFT, padx=(6, 0))

    def _build_run_area(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.start_btn = ttk.Button(frame, text="Start", command=self._start_run)
        self.start_btn.pack(side=tk.LEFT)

        self.stop_btn = ttk.Button(frame, text="Stop", command=self._stop_run, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(frame, text="Chẩn đoán", command=self._run_quick_diagnostics).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(frame, text="Mở thư mục tool", command=self._open_workspace_folder).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(frame, textvariable=self.status_var, foreground="#0b5ed7").pack(side=tk.LEFT, padx=(12, 0))

    def _build_log_area(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Log", padding=8)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(frame, height=12, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def _choose_session_path(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Chọn file session",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.session_path_var.set(path)

    def _choose_coccoc_exe(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn browser.exe của Cốc Cốc",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.coccoc_exe_var.set(path)

    def _choose_coccoc_user_data(self) -> None:
        path = filedialog.askdirectory(
            title="Chọn thư mục User Data của Cốc Cốc",
            initialdir=self.coccoc_user_data_var.get() or str(Path.home()),
        )
        if path:
            self.coccoc_user_data_var.set(path)
            self._refresh_coccoc_profiles()

    def _refresh_coccoc_profiles(self, initial: bool = False) -> None:
        user_data = Path(self.coccoc_user_data_var.get().strip()).expanduser()
        profiles = detect_coccoc_profiles(user_data)

        self.coccoc_profile_map.clear()
        labels: list[str] = []
        for label, profile_dir in profiles:
            labels.append(label)
            self.coccoc_profile_map[label] = profile_dir

        if not labels:
            labels = ["Profile 4", "Profile 1", "Profile"]
            for raw in labels:
                self.coccoc_profile_map[raw] = raw

        self.profile_combo["values"] = labels

        current = self.coccoc_profile_label_var.get().strip()
        if current and current in self.coccoc_profile_map:
            return

        selected = self._find_a1_label(labels)
        if not selected:
            selected = labels[0]
        self.coccoc_profile_label_var.set(selected)

        if not initial:
            self._append_log(f"[GUI] Quét profile xong: {len(labels)} profile")

    def _find_a1_label(self, labels: list[str]) -> str:
        for label in labels:
            if "a1" in label.lower():
                return label
        return ""

    def _select_a1_profile(self) -> None:
        labels = list(self.profile_combo["values"])
        selected = self._find_a1_label(labels)
        if selected:
            self.coccoc_profile_label_var.set(selected)
            self._append_log(f"[GUI] Đã chọn profile: {selected}")
            return

        messagebox.showwarning("A1", "Không tìm thấy profile A1. Hãy bấm Quét profile và kiểm tra lại.")

    def _register_drag_drop(self) -> None:
        if windnd is None:
            self._append_log("[GUI] Kéo-thả chưa bật: thiếu thư viện windnd")
            return

        try:
            windnd.hook_dropfiles(self.root, func=self._on_drop_files)
            self._append_log("[GUI] Đã bật kéo-thả file vào cửa sổ")
        except Exception as error:
            self._append_log(f"[GUI] Không bật được kéo-thả: {error}")

    def _decode_drop_item(self, item) -> str:
        if isinstance(item, str):
            raw = item
        else:
            raw = None
            for encoding in ("utf-8", "mbcs", "cp1258", "latin-1"):
                try:
                    raw = item.decode(encoding)
                    break
                except Exception:
                    continue
            if raw is None:
                raw = str(item)

        return raw.strip().strip('"')

    def _is_media_file(self, path: Path) -> bool:
        return path.suffix.lower() in MEDIA_EXTENSIONS

    def _import_groups_from_txt_path(self, txt_path: Path) -> int:
        try:
            lines = txt_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            try:
                lines = txt_path.read_text(encoding="utf-8-sig").splitlines()
            except Exception:
                lines = txt_path.read_text(encoding="cp1258", errors="ignore").splitlines()

        added = 0
        for line in lines:
            candidate = line.strip()
            if not candidate:
                continue
            try:
                if self._add_group_value(candidate):
                    added += 1
            except Exception:
                continue

        return added

    def _on_drop_files(self, files) -> None:
        dropped_paths: list[Path] = []
        for item in files:
            decoded = self._decode_drop_item(item)
            if not decoded:
                continue
            dropped_paths.append(Path(decoded).expanduser())

        if not dropped_paths:
            return

        media_files: list[Path] = []
        txt_files: list[Path] = []
        for path in dropped_paths:
            if path.is_file() and self._is_media_file(path):
                media_files.append(path)
            elif path.is_file() and path.suffix.lower() == ".txt":
                txt_files.append(path)

        if media_files:
            first = media_files[0].resolve()
            self.video_path_var.set(str(first))
            self._append_log(f"[DROP] Media: {first}")

            if len(media_files) > 1:
                self._append_log(
                    f"[DROP] Có {len(media_files)} media. Có thể chọn nhóm rồi bấm 'Xếp lịch theo nhóm chọn'."
                )

        for txt_file in txt_files:
            try:
                added = self._import_groups_from_txt_path(txt_file)
                self._append_log(f"[DROP] Import nhóm từ {txt_file.name}: thêm {added} nhóm")
            except Exception as error:
                self._append_log(f"[DROP] Lỗi import {txt_file}: {error}")

    def _choose_video_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn media (video/hình)",
            filetypes=[
                ("Media", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("Video", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("Image", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.video_path_var.set(path)

    def _set_schedule_after_minutes(self, minutes: int) -> None:
        target = datetime.now()
        if minutes > 0:
            target = target + timedelta(minutes=minutes)
        self.schedule_at_var.set(target.strftime("%Y-%m-%d %H:%M"))

    def _current_audience_value(self) -> str:
        label = self.audience_var.get().strip()
        value = AUDIENCE_LABEL_TO_VALUE.get(label, AUDIENCE_DEFAULT)
        return normalize_audience(value)

    def _audience_label_for_value(self, value: str | None) -> str:
        normalized = normalize_audience(value)
        return AUDIENCE_VALUE_TO_LABEL.get(normalized, AUDIENCE_VALUE_TO_LABEL[AUDIENCE_DEFAULT])

    def _set_audience_editor_value(self, value: str | None) -> None:
        self.audience_var.set(self._audience_label_for_value(value))

    def _queue_selected_groups_with_step(self) -> None:
        selected = self.group_listbox.curselection()
        if not selected:
            messagebox.showwarning("Xếp lịch", "Hãy chọn ít nhất 1 nhóm để xếp lịch")
            return

        try:
            step_minutes = self._parse_int("Bước lịch", self.schedule_step_minutes_var.get())
        except Exception as error:
            messagebox.showerror("Xếp lịch", str(error))
            return

        try:
            schedule_text, resolved_video, caption, _ = self._validate_post_input()
        except Exception as error:
            messagebox.showerror("Dữ liệu không hợp lệ", str(error))
            return

        audience = self._current_audience_value()
        audience_label = self._audience_label_for_value(audience)

        if schedule_text:
            start_time = parse_datetime(schedule_text)
        else:
            start_time = datetime.now()

        selected_groups = [self.group_listbox.get(idx) for idx in selected]

        for index, group_url in enumerate(selected_groups):
            schedule_time = start_time + timedelta(minutes=step_minutes * index)
            iid = f"task_{self.task_id_counter}"
            self.task_id_counter += 1

            self.task_store[iid] = {
                "group_url": group_url,
                "video_path": str(resolved_video),
                "caption": caption,
                "schedule_at": schedule_time.strftime("%Y-%m-%d %H:%M"),
                "audience": audience,
            }

            self.task_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    group_url,
                    resolved_video.name,
                    schedule_time.strftime("%Y-%m-%d %H:%M"),
                    audience_label,
                    "pending",
                ),
            )

        self._append_log(f"[GUI] Đã xếp lịch {len(selected_groups)} nhóm, cách nhau {step_minutes} phút")

    def _get_first_selected_task_iid(self) -> str | None:
        selected = self.task_tree.selection()
        if not selected:
            return None
        return selected[0]

    def _load_selected_task_for_edit(self, _event=None) -> None:
        iid = self._get_first_selected_task_iid()
        if not iid:
            return

        task = self.task_store.get(iid)
        if not task:
            return

        self.video_path_var.set(task.get("video_path", ""))
        self.schedule_at_var.set(task.get("schedule_at", ""))
        self._set_audience_editor_value(task.get("audience", AUDIENCE_DEFAULT))

        self.caption_text.delete("1.0", tk.END)
        self.caption_text.insert("1.0", task.get("caption", ""))

        group_url = task.get("group_url", "")
        all_groups = self.group_listbox.get(0, tk.END)
        if group_url in all_groups:
            index = all_groups.index(group_url)
            self.group_listbox.selection_clear(0, tk.END)
            self.group_listbox.selection_set(index)
            self.group_listbox.see(index)

        self.editing_task_iid = iid
        self._append_log(f"[GUI] Đã nạp dòng để sửa: {iid}")

    def _update_selected_task(self) -> None:
        iid = self._get_first_selected_task_iid() or self.editing_task_iid
        if not iid:
            messagebox.showwarning("Sửa task", "Hãy chọn 1 dòng trong hàng đợi để cập nhật")
            return

        task = self.task_store.get(iid)
        if not task:
            messagebox.showerror("Sửa task", "Không tìm thấy dữ liệu dòng đã chọn")
            return

        try:
            schedule_text, resolved_video, caption, _ = self._validate_post_input()
        except Exception as error:
            messagebox.showerror("Dữ liệu không hợp lệ", str(error))
            return

        task["video_path"] = str(resolved_video)
        task["caption"] = caption
        task["schedule_at"] = schedule_text
        task["audience"] = self._current_audience_value()

        old_group = task.get("group_url", "")
        selected_group_indices = self.group_listbox.curselection()
        if selected_group_indices:
            task["group_url"] = self.group_listbox.get(selected_group_indices[0])
        elif not old_group:
            messagebox.showwarning("Sửa task", "Không xác định được group_url cho dòng này")
            return

        schedule_display = task["schedule_at"] if task["schedule_at"] else "Đăng ngay"
        self.task_tree.item(
            iid,
            values=(
                task["group_url"],
                Path(task["video_path"]).name,
                schedule_display,
                self._audience_label_for_value(task.get("audience", AUDIENCE_DEFAULT)),
                "pending",
            ),
        )

        self._append_log(f"[GUI] Đã cập nhật dòng: {iid}")

    def _duplicate_selected_tasks(self) -> None:
        selected = self.task_tree.selection()
        if not selected:
            messagebox.showwarning("Nhân đôi", "Hãy chọn ít nhất 1 dòng trong hàng đợi")
            return

        created = 0
        for iid in selected:
            task = self.task_store.get(iid)
            if not task:
                continue

            new_iid = f"task_{self.task_id_counter}"
            self.task_id_counter += 1

            copied = {
                "group_url": task.get("group_url", ""),
                "video_path": task.get("video_path", ""),
                "caption": task.get("caption", ""),
                "schedule_at": task.get("schedule_at", ""),
                "audience": normalize_audience(task.get("audience", AUDIENCE_DEFAULT)),
            }
            self.task_store[new_iid] = copied

            schedule_display = copied["schedule_at"] if copied["schedule_at"] else "Đăng ngay"
            self.task_tree.insert(
                "",
                tk.END,
                iid=new_iid,
                values=(
                    copied["group_url"],
                    Path(copied["video_path"]).name,
                    schedule_display,
                    self._audience_label_for_value(copied.get("audience", AUDIENCE_DEFAULT)),
                    "pending",
                ),
            )
            created += 1

        self._append_log(f"[GUI] Đã nhân đôi {created} dòng")

    def _apply_schedule_to_selected_tasks(self) -> None:
        selected = self.task_tree.selection()
        if not selected:
            messagebox.showwarning("Giờ đăng", "Hãy chọn ít nhất 1 dòng trong hàng đợi")
            return

        schedule_text = self.schedule_at_var.get().strip()
        if schedule_text:
            try:
                parse_datetime(schedule_text)
            except Exception as error:
                messagebox.showerror("Giờ đăng", f"Định dạng giờ không hợp lệ:\n{error}")
                return

        updated = 0
        for iid in selected:
            task = self.task_store.get(iid)
            if not task:
                continue

            task["schedule_at"] = schedule_text
            schedule_display = schedule_text if schedule_text else "Đăng ngay"
            values = list(self.task_tree.item(iid, "values"))
            values[2] = schedule_display
            values[4] = "pending"
            self.task_tree.item(iid, values=values)
            updated += 1

        self._append_log(f"[GUI] Đã áp dụng giờ cho {updated} dòng")

    def _apply_schedule_to_all_tasks(self) -> None:
        all_iids = list(self.task_tree.get_children())
        if not all_iids:
            messagebox.showwarning("Giờ đăng", "Chưa có dòng nào trong hàng đợi")
            return

        schedule_text = self.schedule_at_var.get().strip()
        if schedule_text:
            try:
                parse_datetime(schedule_text)
            except Exception as error:
                messagebox.showerror("Giờ đăng", f"Định dạng giờ không hợp lệ:\n{error}")
                return

        updated = 0
        for iid in all_iids:
            task = self.task_store.get(iid)
            if not task:
                continue

            task["schedule_at"] = schedule_text
            schedule_display = schedule_text if schedule_text else "Đăng ngay"
            values = list(self.task_tree.item(iid, "values"))
            values[2] = schedule_display
            values[4] = "pending"
            self.task_tree.item(iid, values=values)
            updated += 1

        self._append_log(f"[GUI] Đã áp dụng giờ cho toàn bộ {updated} dòng")

    def _apply_media_to_selected_tasks(self) -> None:
        selected = self.task_tree.selection()
        if not selected:
            messagebox.showwarning("Media", "Hãy chọn ít nhất 1 dòng trong hàng đợi")
            return

        media_raw = self.video_path_var.get().strip()
        if not media_raw:
            messagebox.showwarning("Media", "Hãy chọn hoặc kéo-thả media trước")
            return

        media_path = Path(media_raw).expanduser().resolve()
        if not media_path.exists() or not media_path.is_file():
            messagebox.showerror("Media", f"Không tìm thấy media:\n{media_path}")
            return

        if not self._is_media_file(media_path):
            messagebox.showwarning("Media", "File hiện tại không phải định dạng media hỗ trợ")
            return

        updated = 0
        for iid in selected:
            task = self.task_store.get(iid)
            if not task:
                continue

            task["video_path"] = str(media_path)
            values = list(self.task_tree.item(iid, "values"))
            values[1] = media_path.name
            values[4] = "pending"
            self.task_tree.item(iid, values=values)
            updated += 1

        self._append_log(f"[GUI] Đã áp dụng media cho {updated} dòng")

    def _apply_selected_group_to_selected_tasks(self) -> None:
        selected_tasks = self.task_tree.selection()
        if not selected_tasks:
            messagebox.showwarning("Nhóm", "Hãy chọn ít nhất 1 dòng trong hàng đợi")
            return

        selected_groups = self.group_listbox.curselection()
        if not selected_groups:
            messagebox.showwarning("Nhóm", "Hãy chọn 1 nhóm ở danh sách nhóm bên trái")
            return

        group_url = self.group_listbox.get(selected_groups[0])

        updated = 0
        for iid in selected_tasks:
            task = self.task_store.get(iid)
            if not task:
                continue
            task["group_url"] = group_url

            values = list(self.task_tree.item(iid, "values"))
            values[0] = group_url
            values[4] = "pending"
            self.task_tree.item(iid, values=values)
            updated += 1

        self._append_log(f"[GUI] Đã áp dụng nhóm cho {updated} dòng")

    def _apply_audience_to_selected_tasks(self) -> None:
        selected_tasks = self.task_tree.selection()
        if not selected_tasks:
            messagebox.showwarning("Riêng tư", "Hãy chọn ít nhất 1 dòng trong hàng đợi")
            return

        audience = self._current_audience_value()
        audience_label = self._audience_label_for_value(audience)

        updated = 0
        for iid in selected_tasks:
            task = self.task_store.get(iid)
            if not task:
                continue

            task["audience"] = audience
            values = list(self.task_tree.item(iid, "values"))
            values[3] = audience_label
            values[4] = "pending"
            self.task_tree.item(iid, values=values)
            updated += 1

        self._append_log(f"[GUI] Đã áp dụng quyền riêng tư '{audience_label}' cho {updated} dòng")

    def _add_group_value(self, group_url: str) -> bool:
        raw = group_url.strip()
        if not raw:
            return False

        existing = set(self.group_listbox.get(0, tk.END))
        if raw in existing:
            return False

        if not raw.startswith("http"):
            raise ValueError("Group URL nên bắt đầu bằng http/https.")

        self.group_listbox.insert(tk.END, raw)
        return True

    def _add_group(self) -> None:
        raw = self.group_url_var.get().strip()
        if not raw:
            return

        try:
            added = self._add_group_value(raw)
        except Exception as error:
            messagebox.showwarning("URL", str(error))
            return

        if not added:
            messagebox.showinfo("Trùng", "Group URL này đã có trong danh sách.")
            return

        self.group_url_var.set("")

    def _load_ww_groups(self, silent: bool = False) -> None:
        added = 0
        for group_url in WW_GROUP_PRESET:
            try:
                if self._add_group_value(group_url):
                    added += 1
            except Exception:
                continue

        if not silent:
            self._append_log(f"[GUI] Đã nạp nhóm WW: thêm {added}/{len(WW_GROUP_PRESET)} nhóm")

    def _add_personal_profile_target(self) -> None:
        try:
            added = self._add_group_value(PERSONAL_PROFILE_URL)
        except Exception as error:
            messagebox.showerror("Trang cá nhân", str(error))
            return

        if added:
            self._append_log("[GUI] Đã thêm đích Trang cá nhân (facebook.com/me)")
        else:
            messagebox.showinfo("Trang cá nhân", "Đích trang cá nhân đã có sẵn trong danh sách")

    def _on_group_selected(self, _event=None) -> None:
        selected = self.group_listbox.curselection()
        if not selected:
            return
        self.group_url_var.set(self.group_listbox.get(selected[0]))

    def _update_selected_group_from_entry(self) -> None:
        selected = self.group_listbox.curselection()
        if not selected:
            messagebox.showwarning("Nhóm", "Hãy chọn 1 nhóm để cập nhật")
            return

        new_url = self.group_url_var.get().strip()
        if not new_url:
            messagebox.showwarning("Nhóm", "Ô Group URL đang trống")
            return

        if not new_url.startswith("http"):
            messagebox.showwarning("URL", "Group URL nên bắt đầu bằng http/https")
            return

        first_idx = selected[0]
        current_urls = list(self.group_listbox.get(0, tk.END))
        for idx in selected:
            current_urls[idx] = new_url

        self.group_listbox.delete(0, tk.END)
        for url in current_urls:
            self.group_listbox.insert(tk.END, url)

        self.group_listbox.selection_clear(0, tk.END)
        self.group_listbox.selection_set(first_idx)
        self.group_listbox.see(first_idx)

        self._append_log(f"[GUI] Đã cập nhật {len(selected)} nhóm thành: {new_url}")

    def _open_selected_group(self) -> None:
        selected = self.group_listbox.curselection()
        if not selected:
            messagebox.showwarning("Nhóm", "Hãy chọn 1 nhóm để mở")
            return

        group_url = self.group_listbox.get(selected[0])
        try:
            webbrowser.open(group_url)
        except Exception as error:
            messagebox.showerror("Mở nhóm", f"Không mở được link:\n{error}")

    def _remove_selected_groups(self) -> None:
        indices = list(self.group_listbox.curselection())
        for idx in reversed(indices):
            self.group_listbox.delete(idx)

    def _select_all_groups(self) -> None:
        count = self.group_listbox.size()
        if count <= 0:
            return
        self.group_listbox.selection_set(0, count - 1)

    def _clear_group_selection(self) -> None:
        self.group_listbox.selection_clear(0, tk.END)

    def _clear_groups(self) -> None:
        self.group_listbox.delete(0, tk.END)

    def _import_groups_txt(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Import danh sách nhóm từ TXT",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if not file_path:
            return

        try:
            added = self._import_groups_from_txt_path(Path(file_path))
        except Exception as error:
            messagebox.showerror("Lỗi", f"Không đọc được file:\n{error}")
            return

        messagebox.showinfo("Import", f"Đã thêm {added} nhóm.")

    def _export_groups_txt(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export danh sách nhóm",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        groups = list(self.group_listbox.get(0, tk.END))
        try:
            Path(path).write_text("\n".join(groups), encoding="utf-8")
            self._append_log(f"[GUI] Đã export {len(groups)} nhóm: {path}")
        except Exception as error:
            messagebox.showerror("Export", f"Không lưu được file:\n{error}")

    def _validate_post_input(self) -> tuple[str, Path, str, str]:
        groups = self.group_listbox.get(0, tk.END)
        if not groups:
            raise ValueError("Chưa có nhóm nào trong danh sách")

        video_path = self.video_path_var.get().strip()
        if not video_path:
            raise ValueError("Chưa chọn media")

        resolved_video = Path(video_path).expanduser().resolve()
        if not resolved_video.exists():
            raise ValueError(f"Không tìm thấy media: {resolved_video}")
        if not self._is_media_file(resolved_video):
            raise ValueError("Định dạng media chưa hỗ trợ (hãy dùng video/hình phổ biến)")

        schedule_text = self.schedule_at_var.get().strip()
        if schedule_text:
            parse_datetime(schedule_text)

        caption = self.caption_text.get("1.0", tk.END).strip()
        return schedule_text, resolved_video, caption, video_path

    def _add_task_for_selected_groups(self) -> None:
        selected = self.group_listbox.curselection()
        if not selected:
            messagebox.showwarning("Chọn nhóm", "Hãy chọn ít nhất 1 nhóm ở panel bên trái")
            return

        selected_groups = [self.group_listbox.get(idx) for idx in selected]
        self._add_tasks_for_groups(selected_groups)

    def _add_task_for_all_groups(self) -> None:
        groups = list(self.group_listbox.get(0, tk.END))
        if not groups:
            messagebox.showwarning("Nhóm", "Chưa có nhóm để thêm task")
            return
        self._add_tasks_for_groups(groups)

    def _add_tasks_for_groups(self, groups: list[str]) -> None:
        try:
            schedule_text, resolved_video, caption, _ = self._validate_post_input()
        except Exception as error:
            messagebox.showerror("Dữ liệu không hợp lệ", str(error))
            return

        audience = self._current_audience_value()
        audience_label = self._audience_label_for_value(audience)

        for group_url in groups:
            iid = f"task_{self.task_id_counter}"
            self.task_id_counter += 1

            self.task_store[iid] = {
                "group_url": group_url,
                "video_path": str(resolved_video),
                "caption": caption,
                "schedule_at": schedule_text,
                "audience": audience,
            }

            schedule_display = schedule_text if schedule_text else "Đăng ngay"
            self.task_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    group_url,
                    resolved_video.name,
                    schedule_display,
                    audience_label,
                    "pending",
                ),
            )

        self._append_log(f"[GUI] Đã thêm {len(groups)} task vào hàng đợi")

    def _remove_selected_tasks(self) -> None:
        selected = self.task_tree.selection()
        if not selected:
            return

        for iid in selected:
            self.task_tree.delete(iid)
            self.task_store.pop(iid, None)
            if self.editing_task_iid == iid:
                self.editing_task_iid = None

    def _clear_tasks(self) -> None:
        for iid in self.task_tree.get_children():
            self.task_tree.delete(iid)
        self.task_store.clear()
        self.editing_task_iid = None

    def _save_plan(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Lưu plan",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        plan = {
            "groups": list(self.group_listbox.get(0, tk.END)),
            "tasks": [self.task_store[iid] for iid in self.task_tree.get_children()],
            "settings": {
                "session_path": self.session_path_var.get(),
                "min_delay": self.min_delay_var.get(),
                "max_delay": self.max_delay_var.get(),
                "slow_mo": self.slow_mo_var.get(),
                "timeout": self.timeout_var.get(),
                "locale": self.locale_var.get(),
                "timezone": self.timezone_var.get(),
                "schedule_step_minutes": self.schedule_step_minutes_var.get(),
                "default_audience": self._current_audience_value(),
                "headless": self.headless_var.get(),
                "dry_run": self.dry_run_var.get(),
                "use_coccoc": self.use_coccoc_var.get(),
                "coccoc_exe": self.coccoc_exe_var.get(),
                "coccoc_user_data": self.coccoc_user_data_var.get(),
                "coccoc_profile_label": self.coccoc_profile_label_var.get(),
            },
        }

        try:
            Path(path).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            self._append_log(f"[GUI] Đã lưu plan: {path}")
        except Exception as error:
            messagebox.showerror("Lỗi", f"Không lưu được plan:\n{error}")

    def _load_plan(self) -> None:
        path = filedialog.askopenfilename(
            title="Mở plan",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as error:
            messagebox.showerror("Lỗi", f"Không mở được plan:\n{error}")
            return

        self._clear_groups()
        for group in data.get("groups", []):
            if isinstance(group, str) and group.strip():
                self.group_listbox.insert(tk.END, group.strip())

        self._clear_tasks()
        tasks = data.get("tasks", [])
        for task in tasks:
            if not isinstance(task, dict):
                continue
            group_url = (task.get("group_url") or "").strip()
            video_path = (task.get("video_path") or "").strip()
            caption = task.get("caption") or ""
            schedule_at = (task.get("schedule_at") or "").strip()
            audience = normalize_audience(task.get("audience", AUDIENCE_DEFAULT))

            if not group_url or not video_path:
                continue

            iid = f"task_{self.task_id_counter}"
            self.task_id_counter += 1

            self.task_store[iid] = {
                "group_url": group_url,
                "video_path": video_path,
                "caption": caption,
                "schedule_at": schedule_at,
                "audience": audience,
            }

            display_schedule = schedule_at if schedule_at else "Đăng ngay"
            self.task_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    group_url,
                    Path(video_path).name,
                    display_schedule,
                    self._audience_label_for_value(audience),
                    "pending",
                ),
            )

        settings = data.get("settings", {})
        self.session_path_var.set(settings.get("session_path", self.session_path_var.get()))
        self.min_delay_var.set(str(settings.get("min_delay", self.min_delay_var.get())))
        self.max_delay_var.set(str(settings.get("max_delay", self.max_delay_var.get())))
        self.slow_mo_var.set(str(settings.get("slow_mo", self.slow_mo_var.get())))
        self.timeout_var.set(str(settings.get("timeout", self.timeout_var.get())))
        self.locale_var.set(settings.get("locale", self.locale_var.get()))
        self.timezone_var.set(settings.get("timezone", self.timezone_var.get()))
        self.schedule_step_minutes_var.set(
            str(settings.get("schedule_step_minutes", self.schedule_step_minutes_var.get()))
        )
        self._set_audience_editor_value(settings.get("default_audience", AUDIENCE_DEFAULT))
        self.headless_var.set(bool(settings.get("headless", self.headless_var.get())))
        self.dry_run_var.set(bool(settings.get("dry_run", self.dry_run_var.get())))

        self.use_coccoc_var.set(bool(settings.get("use_coccoc", self.use_coccoc_var.get())))
        self.coccoc_exe_var.set(settings.get("coccoc_exe", self.coccoc_exe_var.get()))
        self.coccoc_user_data_var.set(settings.get("coccoc_user_data", self.coccoc_user_data_var.get()))

        self._refresh_coccoc_profiles()
        preferred_label = settings.get("coccoc_profile_label", "")
        if preferred_label in self.coccoc_profile_map:
            self.coccoc_profile_label_var.set(preferred_label)
        else:
            self._select_a1_profile()

        self._append_log(f"[GUI] Đã nạp plan: {path}")

    def _parse_int(self, name: str, value: str) -> int:
        raw = value.strip()
        if not raw:
            raise ValueError(f"{name} đang trống")
        number = int(raw)
        if number < 0:
            raise ValueError(f"{name} phải >= 0")
        return number

    def _build_tasks_for_runner(self) -> list[PostTask]:
        ordered_iids = list(self.task_tree.get_children())
        if not ordered_iids:
            raise ValueError("Hàng đợi đang trống")

        tasks: list[PostTask] = []

        for row_number, iid in enumerate(ordered_iids, start=1):
            raw = self.task_store.get(iid)
            if not raw:
                continue

            group_url = raw["group_url"]
            video_path = Path(raw["video_path"]).expanduser().resolve()
            caption = raw.get("caption", "")
            schedule_text = (raw.get("schedule_at") or "").strip()
            audience = normalize_audience(raw.get("audience", AUDIENCE_DEFAULT))
            schedule_at = parse_datetime(schedule_text) if schedule_text else None

            if not video_path.exists():
                raise FileNotFoundError(f"Không tìm thấy media: {video_path}")

            tasks.append(
                PostTask(
                    row_number=row_number,
                    group_url=group_url,
                    video_path=video_path,
                    caption=caption,
                    schedule_at=schedule_at,
                    audience=audience,
                )
            )

        if not tasks:
            raise ValueError("Không có task hợp lệ")

        return tasks

    def _selected_profile_directory(self) -> str:
        label = self.coccoc_profile_label_var.get().strip()
        if not label:
            return ""

        if label in self.coccoc_profile_map:
            return self.coccoc_profile_map[label]

        return label

    def _build_runner_config(self) -> RunnerConfig:
        min_delay = self._parse_int("Delay min", self.min_delay_var.get())
        max_delay = self._parse_int("Delay max", self.max_delay_var.get())
        slow_mo = self._parse_int("SlowMo", self.slow_mo_var.get())
        timeout = self._parse_int("Post timeout", self.timeout_var.get())

        session_path = Path(self.session_path_var.get().strip() or ".fb_session.json").expanduser().resolve()

        config = RunnerConfig(
            session_path=session_path,
            min_delay=min_delay,
            max_delay=max_delay,
            slow_mo_ms=slow_mo,
            post_timeout_ms=timeout,
            headless=self.headless_var.get(),
            locale=self.locale_var.get().strip() or "vi-VN",
            timezone_id=self.timezone_var.get().strip() or "Asia/Ho_Chi_Minh",
            interactive_login=False,
            login_wait_timeout_seconds=0,
        )

        if self.use_coccoc_var.get():
            exe_path = Path(self.coccoc_exe_var.get().strip()).expanduser()
            user_data = Path(self.coccoc_user_data_var.get().strip()).expanduser()
            profile_dir = self._selected_profile_directory()

            if not exe_path.exists():
                raise FileNotFoundError(f"Không tìm thấy Cốc Cốc exe: {exe_path}")
            if not user_data.exists():
                raise FileNotFoundError(f"Không tìm thấy User Data: {user_data}")
            if not profile_dir:
                raise ValueError("Chưa chọn profile Cốc Cốc")

            config.browser_executable_path = str(exe_path.resolve())
            config.user_data_dir = user_data.resolve()
            config.profile_directory = profile_dir

        return config

    def _start_run(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Đang chạy", "Tool đang chạy, hãy Stop trước.")
            return

        try:
            tasks = self._build_tasks_for_runner()
            config = self._build_runner_config()
        except Exception as error:
            messagebox.showerror("Dữ liệu không hợp lệ", str(error))
            return

        if self.use_coccoc_var.get():
            profile_dir = config.profile_directory or ""
            self._append_log(f"[GUI] Sẽ mở Cốc Cốc profile: {profile_dir}")
            self._append_log("[GUI] Nếu lỗi profile locked, hãy tắt hết Cốc Cốc rồi Start lại")

        self.stop_event.clear()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.status_var.set("Đang chạy...")

        for iid in self.task_tree.get_children():
            values = list(self.task_tree.item(iid, "values"))
            values[4] = "pending"
            self.task_tree.item(iid, values=values)

        def worker() -> None:
            try:
                stats = run_tasks(
                    tasks,
                    config,
                    dry_run=self.dry_run_var.get(),
                    log_fn=self._thread_log,
                    stop_fn=self.stop_event.is_set,
                    wait_tick_fn=self._thread_tick,
                )
                summary = (
                    f"Hoàn tất | success={stats.success}, failed={stats.failed}, stopped={stats.stopped}"
                )
                self.log_queue.put(("done", summary))
            except Exception as error:
                self.log_queue.put(("error", str(error)))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _stop_run(self) -> None:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return
        self.stop_event.set()
        self.status_var.set("Đang dừng...")
        self._append_log("[GUI] Đã gửi lệnh dừng")

    def _run_quick_diagnostics(self) -> None:
        checks: list[tuple[str, bool, str]] = []

        queue_count = len(self.task_tree.get_children())
        checks.append(("Hàng đợi", queue_count > 0, f"{queue_count} dòng"))

        if self.use_coccoc_var.get():
            exe = Path(self.coccoc_exe_var.get().strip()).expanduser()
            user_data = Path(self.coccoc_user_data_var.get().strip()).expanduser()
            profile = self._selected_profile_directory()

            checks.append(("Cốc Cốc exe", exe.exists(), str(exe)))
            checks.append(("Cốc Cốc User Data", user_data.exists(), str(user_data)))

            profile_path = user_data / profile if profile else user_data
            checks.append(("Profile đã chọn", profile_path.exists(), f"{profile} -> {profile_path}"))

        if queue_count > 0:
            for iid in self.task_tree.get_children():
                task = self.task_store.get(iid, {})
                video_path = Path(task.get("video_path", "")).expanduser()
                checks.append((f"Video {iid}", video_path.exists(), str(video_path)))

        has_error = False
        self._append_log("[DIAG] Bắt đầu kiểm tra nhanh...")
        for name, ok, detail in checks:
            state = "OK" if ok else "ERR"
            if not ok:
                has_error = True
            self._append_log(f"[DIAG] {state} | {name} | {detail}")

        if has_error:
            self.status_var.set("Chẩn đoán có lỗi")
            messagebox.showwarning("Chẩn đoán", "Có mục lỗi. Xem log để biết chi tiết.")
        else:
            self.status_var.set("Chẩn đoán OK")
            messagebox.showinfo("Chẩn đoán", "Tất cả kiểm tra đều OK.")

    def _open_workspace_folder(self) -> None:
        workspace = Path(__file__).resolve().parent
        try:
            import os

            os.startfile(str(workspace))
        except Exception as error:
            messagebox.showerror("Mở thư mục", f"Không mở được thư mục tool:\n{error}")

    def _thread_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _thread_tick(self, seconds_left: int) -> None:
        self.log_queue.put(("tick", str(seconds_left)))

    def _drain_log_queue(self) -> None:
        try:
            while True:
                event_type, payload = self.log_queue.get_nowait()

                if event_type == "log":
                    self._append_log(payload)
                elif event_type == "tick":
                    mins, secs = divmod(max(int(payload), 0), 60)
                    self.status_var.set(f"Đang chờ: {mins:02d}:{secs:02d}")
                elif event_type == "done":
                    self._append_log(f"[GUI] {payload}")
                    self.status_var.set(payload)
                    self.start_btn.configure(state=tk.NORMAL)
                    self.stop_btn.configure(state=tk.DISABLED)
                elif event_type == "error":
                    self._append_log(f"[ERR] {payload}")
                    self.status_var.set("Có lỗi, xem log")
                    self.start_btn.configure(state=tk.NORMAL)
                    self.stop_btn.configure(state=tk.DISABLED)
        except queue.Empty:
            pass

        if self.worker_thread and not self.worker_thread.is_alive():
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)

        self.root.after(150, self._drain_log_queue)

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)


def main() -> None:
    root = tk.Tk()
    FbPosterGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
