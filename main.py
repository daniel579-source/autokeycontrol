import json
import math
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
	import pyautogui
except ImportError:
	pyautogui = None

try:
	import pygetwindow
except ImportError:
	pygetwindow = None

try:
	from PIL import ImageGrab
except ImportError:
	ImageGrab = None

try:
	import pytesseract
except ImportError:
	pytesseract = None

try:
	import cv2
except ImportError:
	cv2 = None

try:
	import numpy as np
except ImportError:
	np = None

APP_VERSION = "v1.0.0"


@dataclass
class Rule:
	name: str
	enabled: bool = True
	priority: int = 10
	condition: str = "interval"
	value: str = "5"
	key: str = "1"
	hold: float = 0.1
	cooldown: float = 1.0
	region: str = "色框2 狀態"
	icon: str = ""
	icon_path: str = ""


CONDITIONS = {
	"interval": "固定間隔",
	"hp_below": "血量低於 (%)",
	"status_missing": "狀態圖示消失",
	"nearest_red_dot": "最近紅點距離小於 (px)",
	"red_dot_navigation": "紅點導航（避開藍點）",
}

VISION_REGIONS = ("色框1 血量", "色框2 狀態", "色框3 地圖")


class VisionReader:
	def __init__(self, app):
		self.app = app

	def screenshot(self, region_name):
		region = self.app.regions.get(region_name)
		return self.screenshot_region(region)

	def screenshot_region(self, region):
		if ImageGrab is None or not region:
			return None
		screen_region = self.app.to_screen_region(region)
		if not screen_region:
			return None
		x, y, width, height = screen_region
		return ImageGrab.grab(bbox=(x, y, x + width, y + height))

	def screenshot_coordinates(self, text):
		try:
			values = tuple(int(item.strip()) for item in text.split(","))
			if len(values) != 4 or ImageGrab is None:
				return None
			x, y, width, height = values
			return ImageGrab.grab(bbox=(x, y, x + width, y + height))
		except ValueError:
			return None

	def hp_percent(self):
		image = self.screenshot("色框1 血量")
		if image is None or pytesseract is None:
			return None
		text = pytesseract.image_to_string(image, config="--psm 7")
		numbers = "".join(char for char in text if char.isdigit() or char == ".")
		try:
			return float(numbers.rstrip("."))
		except ValueError:
			return None

	def status_present(self, region_name, icon_path, threshold=0.8):
		if cv2 is None or np is None or not icon_path:
			return None
		image = self.screenshot(region_name)
		template = cv2.imread(str(icon_path), cv2.IMREAD_COLOR)
		if image is None or template is None:
			return None
		source = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
		if template.shape[0] > source.shape[0] or template.shape[1] > source.shape[1]:
			return False
		result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
		_, score, _, _ = cv2.minMaxLoc(result)
		return score >= threshold

	def nearest_red_dot(self):
		navigation = self.navigation_decision("色框3 地圖", 80)
		return navigation["red_distance"] if navigation else None

	def navigation_decision(self, region_name, avoid_radius):
		image = self.screenshot(region_name)
		if image is None:
			return None
		red_points, blue_points = self.detect_map_points(image)
		if not red_points:
			return None
		width, height = image.size
		center = (width / 2, height / 2)
		red_target = min(red_points, key=lambda point: self.distance(center, point))
		red_distance = self.distance(center, red_target)
		red_vector = (red_target[0] - center[0], red_target[1] - center[1])
		blue_blocking = self.find_blocking_blue(center, red_vector, blue_points, avoid_radius)
		if blue_blocking:
			move_vector = (-blue_blocking[0] + center[0], -blue_blocking[1] + center[1])
			reason = "避開藍點"
		else:
			move_vector = red_vector
			reason = "前往最近紅點"
		return {"direction": self.vector_direction(move_vector), "red_distance": red_distance, "reason": reason}

	def detect_map_points(self, image):
		width, height = image.size
		pixels = image.convert("RGB").load()
		red_points = []
		blue_points = []
		for y in range(0, height, 2):
			for x in range(0, width, 2):
				red, green, blue = pixels[x, y]
				if red > 170 and red > green * 1.45 and red > blue * 1.45:
					red_points.append((x, y))
				elif blue > 130 and blue > red * 1.25 and blue > green * 1.10:
					blue_points.append((x, y))
		return self.cluster_points(red_points), self.cluster_points(blue_points)

	def cluster_points(self, points):
		if not points:
			return []
		clusters = []
		for point in points:
			for cluster in clusters:
				if self.distance(point, cluster[0]) <= 12:
					cluster.append(point)
					break
			else:
				clusters.append([point])
		return [(round(sum(point[0] for point in cluster) / len(cluster)), round(sum(point[1] for point in cluster) / len(cluster))) for cluster in clusters]

	@staticmethod
	def distance(first, second):
		return math.hypot(second[0] - first[0], second[1] - first[1])

	def find_blocking_blue(self, center, red_vector, blue_points, avoid_radius):
		red_length = math.hypot(*red_vector)
		if red_length == 0:
			return None
		red_unit = (red_vector[0] / red_length, red_vector[1] / red_length)
		for blue_point in sorted(blue_points, key=lambda point: self.distance(center, point)):
			blue_vector = (blue_point[0] - center[0], blue_point[1] - center[1])
			forward_distance = blue_vector[0] * red_unit[0] + blue_vector[1] * red_unit[1]
			lateral_distance = abs(blue_vector[0] * red_unit[1] - blue_vector[1] * red_unit[0])
			if 0 < forward_distance <= avoid_radius and lateral_distance <= avoid_radius * 0.65:
				return blue_point
		return None

	@staticmethod
	def vector_direction(vector):
		if abs(vector[0]) >= abs(vector[1]):
			return "right" if vector[0] > 0 else "left"
		return "down" if vector[1] > 0 else "up"


class AutomationEngine:
	def __init__(self, app):
		self.app = app
		self.reader = VisionReader(app)
		self.thread = None
		self.navigation_thread = None
		self.stop_event = threading.Event()
		self.last_run = {}
		self.started_at = 0.0

	def start(self):
		if self.thread and self.thread.is_alive():
			return
		self.stop_event.clear()
		self.started_at = time.time()
		self.thread = threading.Thread(target=self.run, daemon=True)
		self.thread.start()
		self.navigation_thread = threading.Thread(target=self.run_navigation, daemon=True)
		self.navigation_thread.start()

	def stop(self):
		self.stop_event.set()

	def run(self):
		self.app.set_status("執行中", "#5ee0a0")
		while not self.stop_event.is_set():
			rules = sorted((rule for rule in self.app.rules if rule.enabled and rule.condition != "red_dot_navigation"), key=lambda item: item.priority)
			fired = False
			for rule in rules:
				if self.stop_event.is_set():
					break
				if self.is_ready(rule) and self.condition_matches(rule):
					self.trigger(rule)
					fired = True
					break
			if not fired:
				self.stop_event.wait(0.1)
		self.app.set_status("已停止", "#ffb86b")

	def run_navigation(self):
		while not self.stop_event.is_set():
			navigation_rules = sorted((rule for rule in self.app.rules if rule.enabled and rule.condition == "red_dot_navigation"), key=lambda item: item.priority)
			fired = False
			for rule in navigation_rules:
				if self.stop_event.is_set():
					break
				if self.is_ready(rule) and self.condition_matches(rule):
					self.trigger_navigation_rule(rule)
					fired = True
					break
			if not fired:
				self.stop_event.wait(0.08)

	def trigger_navigation_rule(self, rule):
		self.last_run[rule.name] = time.time()
		self.trigger_navigation(rule)

	def is_ready(self, rule):
		return time.time() - self.last_run.get(rule.name, 0) >= max(0.05, rule.cooldown)

	def condition_matches(self, rule):
		elapsed = time.time() - self.started_at
		if rule.condition == "interval":
			return elapsed >= float(rule.value or 0) or rule.name not in self.last_run
		if rule.condition == "hp_below":
			hp = self.reader.hp_percent()
			return hp is not None and hp <= float(rule.value)
		if rule.condition == "status_missing":
			present = self.reader.status_present(rule.region, rule.icon_path, float(rule.value or 0.8))
			return present is False
		if rule.condition == "nearest_red_dot":
			distance = self.reader.nearest_red_dot()
			return distance is not None and distance <= float(rule.value)
		if rule.condition == "red_dot_navigation":
			decision = self.reader.navigation_decision(rule.region, float(rule.value or 80))
			return decision is not None
		return False

	def trigger(self, rule):
		self.last_run[rule.name] = time.time()
		if rule.condition == "red_dot_navigation":
			self.trigger_navigation(rule)
			return
		key = rule.key
		self.app.log(f"觸發：{rule.name} → {key}")
		if pyautogui is None:
			self.app.log("預覽模式：尚未安裝 pyautogui，未送出按鍵")
			return
		self.app.focus_target()
		pyautogui.keyDown(key)
		time.sleep(max(0, rule.hold))
		pyautogui.keyUp(key)

	def trigger_navigation(self, rule):
		avoid_radius = float(rule.value or 80)
		hold_seconds = max(0.05, rule.hold)
		started = time.monotonic()
		active_key = None
		preview_logged = False
		while not self.stop_event.is_set() and time.monotonic() - started < hold_seconds:
			decision = self.reader.navigation_decision(rule.region, avoid_radius)
			if not decision:
				if active_key and pyautogui is not None:
					pyautogui.keyUp(active_key)
				active_key = None
				self.app.log("導航：色框3 尚未偵測到紅點，暫停移動")
				self.stop_event.wait(0.08)
				continue
			key = self.navigation_key(rule.key, decision["direction"])
			if key != active_key:
				if active_key and pyautogui is not None:
					pyautogui.keyUp(active_key)
				active_key = key
				self.app.log(f"導航更新：{decision['reason']} → {key}")
				if pyautogui is not None:
					self.app.focus_target()
					pyautogui.keyDown(active_key)
			elif pyautogui is None and not preview_logged:
				self.app.log(f"預覽導航：{decision['reason']} → {key}")
				preview_logged = True
			self.stop_event.wait(min(0.08, max(0.01, hold_seconds - (time.monotonic() - started))))
		if active_key and pyautogui is not None:
			pyautogui.keyUp(active_key)

	@staticmethod
	def navigation_key(mapping, direction):
		keys = [item.strip() for item in mapping.split(",") if item.strip()]
		if len(keys) != 4:
			return direction
		return dict(zip(("left", "right", "up", "down"), keys))[direction]


class App(tk.Tk):
	def __init__(self):
		super().__init__()
		self.title(f"AUTOKEY CONTROL {APP_VERSION}  /  視覺條件自動化")
		self.geometry("1120x720")
		self.minsize(920, 620)
		self.configure(bg="#10161d")
		self.rules = []
		self.regions = {}
		self.region_vars = {}
		self.status_icons = {}
		self.selected_rule_index = None
		self.drag_index = None
		self.resource_dir = Path(__file__).parent / "resources" / "status_icons"
		self.engine = AutomationEngine(self)
		self.protocol("WM_DELETE_WINDOW", self.close)
		self.build_style()
		self.build_ui()

	def build_style(self):
		style = ttk.Style(self)
		style.theme_use("clam")
		style.configure("TFrame", background="#10161d")
		style.configure("Panel.TFrame", background="#17212b")
		style.configure("TLabel", background="#17212b", foreground="#d7e2ea", font=("Segoe UI", 10))
		style.configure("Title.TLabel", background="#10161d", foreground="#f4f7f9", font=("Segoe UI", 22, "bold"))
		style.configure("Sub.TLabel", background="#10161d", foreground="#8fa4b2", font=("Segoe UI", 10))
		style.configure("TButton", background="#263744", foreground="#e9f1f5", padding=(12, 7), borderwidth=0)
		style.map("TButton", background=[("active", "#3b5362")])
		style.configure("Accent.TButton", background="#e36d4f", foreground="white", font=("Segoe UI", 10, "bold"))
		style.map("Accent.TButton", background=[("active", "#f48a68")])
		style.configure("Treeview", background="#111a22", fieldbackground="#111a22", foreground="#d7e2ea", rowheight=32, borderwidth=0)
		style.configure("Treeview.Heading", background="#263744", foreground="#b8cbd4", relief="flat")

	def build_ui(self):
		header = ttk.Frame(self)
		header.pack(fill="x", padx=28, pady=(24, 14))
		ttk.Label(header, text="AUTOKEY CONTROL", style="Title.TLabel").pack(anchor="w")
		ttk.Label(header, text="用視覺條件驅動按鍵規則，讓長時間操作保持可控、可追蹤。", style="Sub.TLabel").pack(anchor="w", pady=(3, 0))

		toolbar = ttk.Frame(self)
		toolbar.pack(fill="x", padx=28, pady=(0, 14))
		ttk.Label(toolbar, text="目標視窗標題").pack(side="left")
		self.target_var = tk.StringVar()
		ttk.Entry(toolbar, textvariable=self.target_var, width=28).pack(side="left", padx=(10, 8))
		ttk.Button(toolbar, text="重新整理視窗", command=self.refresh_windows).pack(side="left")
		self.window_var = tk.StringVar(value="尚未選擇")
		self.window_combo = ttk.Combobox(toolbar, textvariable=self.window_var, state="readonly", width=32)
		self.window_combo.pack(side="left", padx=8)
		self.window_combo.bind("<<ComboboxSelected>>", self.on_window_selected)
		ttk.Button(toolbar, text="儲存設定", command=self.save).pack(side="right", padx=(8, 0))
		ttk.Button(toolbar, text="載入設定", command=self.load).pack(side="right")

		body = ttk.Frame(self)
		body.pack(fill="both", expand=True, padx=28, pady=(0, 20))
		left = ttk.Frame(body, style="Panel.TFrame", padding=16)
		left.pack(side="left", fill="both", expand=True)
		right = ttk.Frame(body, style="Panel.TFrame", padding=16)
		right.pack(side="right", fill="y", padx=(16, 0))
		ttk.Label(left, text="規則優先序", font=("Segoe UI", 13, "bold")).pack(anchor="w")
		ttk.Label(left, text="卡片由上到下執行；使用上移 / 下移調整優先順序。", foreground="#8fa4b2").pack(anchor="w", pady=(3, 12))
		self.cards_frame = ttk.Frame(left, style="Panel.TFrame")
		self.cards_frame.pack(fill="both", expand=True)
		actions = ttk.Frame(left)
		actions.pack(fill="x", pady=(12, 0))
		ttk.Button(actions, text="新增規則", command=self.new_rule).pack(side="left")
		ttk.Button(actions, text="套用編輯", command=self.update_rule).pack(side="left", padx=8)
		ttk.Button(actions, text="刪除規則", command=self.delete_rule).pack(side="left")

		ttk.Label(right, text="規則編輯器", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
		self.fields = {}
		self.field_widgets = {}
		field_defs = [("name", "名稱"), ("priority", "優先度"), ("condition", "條件"), ("value", "數值 / 門檻"), ("key", "按鍵 / 導航按鍵"), ("hold", "按住秒數"), ("cooldown", "冷卻秒數"), ("region", "判斷色框"), ("icon", "圖示資源")]
		for row, (key, label) in enumerate(field_defs, 1):
			ttk.Label(right, text=label).grid(row=row, column=0, sticky="w", pady=6)
			variable = tk.StringVar()
			self.fields[key] = variable
			if key == "name":
				name_field = ttk.Frame(right)
				name_field.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=6)
				widget = ttk.Entry(name_field, textvariable=variable, width=15)
				widget.pack(side="left")
				self.enabled_var = tk.BooleanVar(value=True)
				ttk.Checkbutton(name_field, text="啟用", variable=self.enabled_var).pack(side="left", padx=(10, 0))
			elif key == "condition":
				widget = ttk.Combobox(right, textvariable=variable, state="readonly", values=list(CONDITIONS.values()), width=22)
			elif key == "region":
				widget = ttk.Combobox(right, textvariable=variable, state="readonly", values=VISION_REGIONS, width=22)
			elif key == "icon":
				widget = ttk.Combobox(right, textvariable=variable, state="readonly", values=(), width=22)
			else:
				widget = ttk.Entry(right, textvariable=variable, width=25)
			if key != "name":
				widget.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=6)
			self.field_widgets[key] = widget
		ttk.Separator(right).grid(row=10, column=0, columnspan=2, sticky="ew", pady=5)
		tk.Label(right, text="導航按鍵格式：左,右,上,下，例如 a,d,w,s", foreground="#8fa4b2").grid(row=10, column=1, sticky="w", pady=(0, 5))
		ttk.Label(right, text="視覺區域（相對目標視窗）", font=("Segoe UI", 11, "bold")).grid(row=11, column=0, columnspan=2, sticky="w", pady=(14, 8))
		for row, region in enumerate(("色框1 血量", "色框2 狀態", "色框3 地圖"), 12):
			ttk.Label(right, text=region).grid(row=row, column=0, sticky="w", pady=5)
			variable = tk.StringVar()
			self.region_vars[region] = variable
			field = ttk.Frame(right)
			field.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=5)
			ttk.Entry(field, textvariable=variable, width=17).pack(side="left")
			ttk.Button(field, text="框選", command=lambda name=region: self.select_region(name)).pack(side="left", padx=(5, 0))
		ttk.Label(right, text="格式：相對 x,y,width,height", foreground="#8fa4b2").grid(row=15, column=1, sticky="w", pady=(2, 14))
		ttk.Label(right, text="色框2 狀態圖示（每行一個）", font=("Segoe UI", 11, "bold")).grid(row=16, column=0, columnspan=2, sticky="w", pady=(4, 6))
		status_toolbar = ttk.Frame(right)
		status_toolbar.grid(row=17, column=0, columnspan=2, sticky="ew", pady=(0, 5))
		self.status_name_var = tk.StringVar()
		ttk.Entry(status_toolbar, textvariable=self.status_name_var, width=19).pack(side="left")
		ttk.Button(status_toolbar, text="框選並加入", command=self.select_status_icon).pack(side="left", padx=(5, 0))
		self.status_text = tk.Text(right, height=4, width=35, bg="#111a22", fg="#d7e2ea", insertbackground="white", relief="flat")
		self.status_text.grid(row=18, column=0, columnspan=2, sticky="ew")
		ttk.Label(right, text="輸入狀態名稱後按框選；規則的狀態圖示名稱需相同", foreground="#8fa4b2", wraplength=270).grid(row=19, column=0, columnspan=2, sticky="w", pady=(4, 12))

		footer = ttk.Frame(self)
		footer.pack(fill="x", padx=28, pady=(0, 20))
		self.status_label = ttk.Label(footer, text="●  待命", foreground="#ffb86b")
		self.status_label.pack(side="left")
		self.log_text = tk.Text(footer, height=4, bg="#111a22", fg="#9fb6c2", insertbackground="white", relief="flat", state="disabled")
		self.log_text.pack(side="left", fill="x", expand=True, padx=22)
		ttk.Button(footer, text="開始執行", style="Accent.TButton", command=self.start).pack(side="right")
		ttk.Button(footer, text="停止", command=self.stop).pack(side="right", padx=8)
		self.sample_rules()

	def sample_rules(self):
		self.rules = [Rule("低血量保命", True, 1, "hp_below", "35", "F1", 0.12, 3.0, "色框1 血量"), Rule("補上狀態", True, 2, "status_missing", "0.8", "2", 0.15, 8.0, "色框2 狀態", "護盾"), Rule("紅點導航", True, 3, "red_dot_navigation", "80", "a,d,w,s", 0.12, 0.3, "色框3 地圖"), Rule("週期技能", True, 4, "interval", "5", "3", 0.1, 5.0, "色框3 地圖")]
		self.refresh_tree()
		self.log("已載入範例規則；視覺區域需依遊戲畫面填入座標。")

	def refresh_tree(self):
		for child in self.cards_frame.winfo_children():
			child.destroy()
		for index, rule in enumerate(self.rules):
			card = tk.Frame(self.cards_frame, bg="#111a22", highlightthickness=2, highlightbackground="#2b3d49", padx=10, pady=8)
			card.pack(fill="x", pady=(0, 8))
			card.bind("<Button-1>", lambda _event, value=index: self.select_rule(value))
			card.bind("<ButtonPress-1>", lambda _event, value=index: self.begin_drag(value))
			card.bind("<ButtonRelease-1>", self.finish_drag)
			status = "啟用" if rule.enabled else "停用"
			condition = CONDITIONS.get(rule.condition, rule.condition)
			tk.Label(card, text=f"{index + 1:02d}  {rule.name}", background="#111a22", foreground="#f4f7f9", font=("Segoe UI", 11, "bold")).pack(side="left")
			tk.Label(card, text=f"{status}  |  {condition}", background="#111a22", foreground="#9fb6c2").pack(side="left", padx=12)
			tk.Label(card, text=f"按鍵 {rule.key}  冷卻 {rule.cooldown}s", background="#111a22", foreground="#9fb6c2").pack(side="left")
			enabled_var = tk.BooleanVar(value=rule.enabled)
			ttk.Checkbutton(card, text="啟用", variable=enabled_var, command=lambda value=index, variable=enabled_var: self.toggle_rule(value, variable.get())).pack(side="right", padx=(0, 10))
			ttk.Button(card, text="上移", command=lambda value=index: self.move_rule(value, -1)).pack(side="right")
			ttk.Button(card, text="下移", command=lambda value=index: self.move_rule(value, 1)).pack(side="right", padx=(0, 5))
			for child in card.winfo_children():
				if isinstance(child, tk.Label):
					child.bind("<Button-1>", lambda _event, value=index: self.select_rule(value))
					child.bind("<ButtonPress-1>", lambda _event, value=index: self.begin_drag(value))
					child.bind("<ButtonRelease-1>", self.finish_drag)
			if index == self.selected_rule_index:
				card.configure(highlightbackground="#e36d4f")

	def toggle_rule(self, index, enabled):
		if index < 0 or index >= len(self.rules):
			return
		self.rules[index].enabled = bool(enabled)
		if self.selected_rule_index == index:
			self.enabled_var.set(bool(enabled))
		self.log(f"規則「{self.rules[index].name}」已{'啟用' if enabled else '停用'}")
		self.refresh_tree()

	def select_rule(self, index):
		self.selected_rule_index = index
		self.on_select()
		self.refresh_tree()

	def begin_drag(self, index):
		self.drag_index = index
		self.select_rule(index)

	def finish_drag(self, event):
		if self.drag_index is None:
			return
		start = self.drag_index
		self.drag_index = None
		cards = self.cards_frame.winfo_children()
		if not cards or start >= len(cards):
			return
		pointer_y = event.y_root - self.cards_frame.winfo_rooty()
		target = len(cards) - 1
		for index, card in enumerate(cards):
			midpoint = card.winfo_y() + card.winfo_height() / 2
			if pointer_y < midpoint:
				target = index
				break
		if target == start:
			return
		rule = self.rules.pop(start)
		self.rules.insert(target, rule)
		for position, item in enumerate(self.rules, 1):
			item.priority = position
		self.selected_rule_index = target
		self.refresh_tree()
		self.on_select()

	def move_rule(self, index, direction):
		target = index + direction
		if target < 0 or target >= len(self.rules):
			return
		self.rules[index], self.rules[target] = self.rules[target], self.rules[index]
		self.selected_rule_index = target
		for position, rule in enumerate(self.rules, 1):
			rule.priority = position
		self.refresh_tree()
		self.on_select()

	def on_select(self, _event=None):
		if self.selected_rule_index is None or self.selected_rule_index >= len(self.rules):
			return
		rule = self.rules[self.selected_rule_index]
		for key in self.fields:
			value = CONDITIONS.get(rule.condition, rule.condition) if key == "condition" else getattr(rule, key)
			self.fields[key].set(str(value))
		self.enabled_var.set(rule.enabled)
		self.field_widgets["icon"]["values"] = tuple(self.status_icons.keys())

	def new_rule(self):
		self.rules.append(Rule("新規規則"))
		self.selected_rule_index = len(self.rules) - 1
		self.refresh_tree()
		self.on_select()

	def update_rule(self):
		if self.selected_rule_index is None or self.selected_rule_index >= len(self.rules):
			messagebox.showinfo("提示", "請先選擇要編輯的規則。")
			return
		self.parse_status_icons()
		values = {key: variable.get().strip() for key, variable in self.fields.items()}
		try:
			rule = self.rules[self.selected_rule_index]
			rule.name = values["name"] or "未命名規則"
			rule.priority = int(values["priority"] or 10)
			rule.condition = next((key for key, label in CONDITIONS.items() if label == values["condition"]), values["condition"])
			rule.value = values["value"]
			rule.key = values["key"] or "1"
			rule.hold = float(values["hold"] or 0.1)
			rule.cooldown = float(values["cooldown"] or 1)
			rule.region = values["region"]
			rule.icon = values["icon"]
			rule.icon_path = str(self.status_icons.get(rule.icon, {}).get("path", ""))
			rule.enabled = self.enabled_var.get()
		except (ValueError, IndexError):
			messagebox.showerror("資料格式錯誤", "優先度、按住秒數與冷卻秒數必須是數字。")
			return
		self.refresh_tree()
		self.log(f"已更新規則：{rule.name}")

	def delete_rule(self):
		if self.selected_rule_index is not None and self.selected_rule_index < len(self.rules):
			self.rules.pop(self.selected_rule_index)
			self.selected_rule_index = min(self.selected_rule_index, len(self.rules) - 1) if self.rules else None
			for position, rule in enumerate(self.rules, 1):
				rule.priority = position
			self.refresh_tree()
			self.on_select()

	def parse_regions(self):
		result = {}
		for name, variable in self.region_vars.items():
			try:
				result[name] = tuple(int(item.strip()) for item in variable.get().split(","))
				if len(result[name]) != 4:
					raise ValueError
			except ValueError:
				continue
		self.regions = result

	def parse_status_icons(self):
		result = {}
		for line in self.status_text.get("1.0", "end").splitlines():
			if "=" not in line:
				continue
			name, data = line.split("=", 1)
			try:
				coordinate_text, _, path = data.partition("|")
				values = tuple(int(item.strip()) for item in coordinate_text.split(","))
				if name.strip() and len(values) == 4:
					result[name.strip()] = {"region": values, "path": path.strip()}
			except ValueError:
				continue
		self.status_icons = result

	def start(self):
		self.parse_regions()
		self.parse_status_icons()
		if not self.rules:
			messagebox.showinfo("提示", "請先新增至少一條規則。")
			return
		self.engine.start()

	def stop(self):
		self.engine.stop()

	def set_status(self, text, color):
		self.after(0, lambda: self.status_label.configure(text=f"●  {text}", foreground=color))

	def log(self, text):
		self.after(0, self._append_log, text)

	def _append_log(self, text):
		self.log_text.configure(state="normal")
		self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {text}\n")
		self.log_text.see("end")
		self.log_text.configure(state="disabled")

	def refresh_windows(self):
		if pygetwindow is None:
			self.log("尚未安裝 pygetwindow，請手動輸入視窗標題。")
			return
		titles = [title.strip() for title in pygetwindow.getAllTitles() if title.strip()]
		self.window_combo["values"] = titles
		current = self.target_var.get().strip()
		if current in titles:
			self.window_var.set(current)
		elif self.window_var.get() not in titles:
			self.window_var.set("尚未選擇")
		self.log(f"找到 {len(titles)} 個視窗。")

	def on_window_selected(self, _event=None):
		selected = self.window_var.get().strip()
		if selected and selected != "尚未選擇":
			self.target_var.set(selected)
			self.log(f"目標視窗已選定：{selected}")

	def focus_target(self):
		title = self.target_var.get().strip() or self.window_var.get().strip()
		if pygetwindow is None or not title or title == "尚未選擇":
			return
		windows = pygetwindow.getWindowsWithTitle(title)
		if windows:
			windows[0].activate()

	def target_bounds(self):
		if pygetwindow is None:
			return None
		title = self.target_var.get().strip() or self.window_var.get().strip()
		if not title:
			return None
		windows = pygetwindow.getWindowsWithTitle(title)
		if not windows:
			return None
		window = windows[0]
		return window.left, window.top, window.width, window.height

	def to_screen_region(self, region):
		bounds = self.target_bounds()
		if not bounds or not region or len(region) != 4:
			return None
		left, top, _, _ = bounds
		x, y, width, height = region
		return left + x, top + y, width, height

	def select_region(self, region_name):
		self.open_region_selector(lambda region: self.region_vars[region_name].set(",".join(map(str, region))))

	def select_status_icon(self):
		name = self.status_name_var.get().strip()
		if not name:
			messagebox.showinfo("需要名稱", "請先輸入狀態圖示名稱，例如：護盾。")
			return

		def save_status(region):
			path = self.save_icon_resource(name, region)
			lines = []
			for line in self.status_text.get("1.0", "end").splitlines():
				if "=" in line and line.split("=", 1)[0].strip() != name:
					lines.append(line)
			lines.append(f"{name}={','.join(map(str, region))}|{path}")
			self.status_text.delete("1.0", "end")
			self.status_text.insert("1.0", "\n".join(lines))
			self.status_name_var.set("")

		self.open_region_selector(save_status)

	def save_icon_resource(self, name, region):
		if ImageGrab is None:
			return ""
		screen_region = self.to_screen_region(region)
		if not screen_region:
			return ""
		self.resource_dir.mkdir(parents=True, exist_ok=True)
		path = self.resource_dir / f"{name}.png"
		x, y, width, height = screen_region
		ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(path)
		return str(path)

	def open_region_selector(self, callback):
		bounds = self.target_bounds()
		if not bounds:
			messagebox.showerror("找不到目標視窗", "請先輸入或選擇目標視窗標題，再進行框選。")
			return
		self.focus_target()
		overlay = tk.Toplevel(self)
		overlay.overrideredirect(True)
		overlay.attributes("-topmost", True)
		overlay.attributes("-alpha", 0.28)
		width = overlay.winfo_screenwidth()
		height = overlay.winfo_screenheight()
		overlay.geometry(f"{width}x{height}+0+0")
		canvas = tk.Canvas(overlay, bg="#193342", highlightthickness=0, cursor="crosshair")
		canvas.pack(fill="both", expand=True)
		canvas.create_text(20, 20, anchor="nw", text="拖曳框選區域，按 Esc 取消", fill="white", font=("Segoe UI", 14, "bold"))
		start = [None, None]
		rect = [None]

		def cancel(_event=None):
			overlay.destroy()

		def press(event):
			start[0], start[1] = event.x_root, event.y_root
			rect[0] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#ff8b6b", width=3)

		def move(event):
			if start[0] is not None and rect[0] is not None:
				canvas.coords(rect[0], start[0], start[1], event.x_root, event.y_root)

		def release(event):
			if start[0] is None:
				return
			x1, x2 = sorted((start[0], event.x_root))
			y1, y2 = sorted((start[1], event.y_root))
			left, top, window_width, window_height = bounds
			x1 = max(left, min(x1, left + window_width))
			x2 = max(left, min(x2, left + window_width))
			y1 = max(top, min(y1, top + window_height))
			y2 = max(top, min(y2, top + window_height))
			if x2 - x1 < 2 or y2 - y1 < 2:
				return
			region = (x1 - left, y1 - top, x2 - x1, y2 - y1)
			overlay.destroy()
			callback(region)

		overlay.bind("<Escape>", cancel)
		canvas.bind("<ButtonPress-1>", press)
		canvas.bind("<B1-Motion>", move)
		canvas.bind("<ButtonRelease-1>", release)
		overlay.grab_set()
		overlay.focus_force()

	def save(self):
		path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON 設定", "*.json")])
		if not path:
			return
		self.parse_regions()
		self.parse_status_icons()
		data = {"target": self.target_var.get(), "window": self.window_var.get(), "regions": self.regions, "status_icons": self.status_icons, "rules": [asdict(rule) for rule in self.rules]}
		Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
		self.log(f"設定已儲存：{Path(path).name}")

	def load(self):
		path = filedialog.askopenfilename(filetypes=[("JSON 設定", "*.json")])
		if not path:
			return
		try:
			data = json.loads(Path(path).read_text(encoding="utf-8"))
			self.target_var.set(data.get("target", ""))
			self.window_var.set(data.get("window", "尚未選擇"))
			for key, value in data.get("regions", {}).items():
				self.region_vars.setdefault(key, tk.StringVar()).set(",".join(map(str, value)))
			for region in ("色框1 血量", "色框2 狀態", "色框3 地圖"):
				self.region_vars.setdefault(region, tk.StringVar())
			self.regions = {key: tuple(value) for key, value in data.get("regions", {}).items()}
			self.status_icons = {}
			for key, value in data.get("status_icons", {}).items():
				if isinstance(value, dict):
					self.status_icons[key] = value
				else:
					self.status_icons[key] = {"region": tuple(value), "path": ""}
			self.status_text.delete("1.0", "end")
			self.status_text.insert("1.0", "\n".join(f"{key}={','.join(map(str, value.get('region', ())))}|{value.get('path', '')}" for key, value in self.status_icons.items()))
			self.rules = []
			for item in data.get("rules", []):
				item = dict(item)
				if item.get("condition") == "status_missing" and item.get("region") not in VISION_REGIONS:
					item["icon"] = item.get("region", "")
					item["region"] = "色框2 狀態"
				item.setdefault("icon", "")
				item.setdefault("icon_path", str(self.status_icons.get(item["icon"], {}).get("path", "")))
				self.rules.append(Rule(**item))
			self.refresh_tree()
			self.log(f"設定已載入：{Path(path).name}")
		except (OSError, json.JSONDecodeError, TypeError):
			messagebox.showerror("載入失敗", "設定檔格式不正確。")

	def close(self):
		self.engine.stop()
		self.destroy()


if __name__ == "__main__":
	App().mainloop()
