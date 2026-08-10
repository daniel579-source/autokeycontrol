import json
import math
import random
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

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

IOS_THEME = {
	"background": "#F2F2F7",
	"panel": "#FFFFFF",
	"card": "#FFFFFF",
	"primary": "#007AFF",
	"primary_active": "#5AC8FA",
	"button": "#E5E5EA",
	"button_active": "#D1D1D6",
	"text": "#1C1C1E",
	"secondary": "#636366",
	"muted": "#8E8E93",
	"field": "#FFFFFF",
	"border": "#D1D1D6",
	"success": "#34C759",
	"warning": "#FF9500",
}

THEME_PRESETS = {
	"iOS 淺色": dict(IOS_THEME),
	"iOS 藍灰": {**IOS_THEME, "background": "#EAF2F8", "panel": "#F8FBFF", "card": "#FFFFFF", "primary": "#145DA0", "primary_active": "#3D8AC7"},
}


class IOSSwitch(tk.Frame):
	WIDTH = 48
	HEIGHT = 28
	KNOB = 22

	def __init__(self, parent, variable, command=None):
		try:
			background = parent.cget("background")
		except tk.TclError:
			background = IOS_THEME["background"]
		super().__init__(parent, width=self.WIDTH, height=self.HEIGHT, bg=background, highlightthickness=0, padx=0, pady=0)
		self.pack_propagate(False)
		self.variable = variable
		self.command = command
		self.canvas = tk.Canvas(self, width=self.WIDTH, height=self.HEIGHT, bg=self.cget("background"), highlightthickness=0, cursor="hand2")
		self.canvas.pack()
		self.canvas.bind("<Button-1>", self.toggle)
		self.canvas.bind("<Key-space>", self.toggle)
		self.canvas.bind("<Key-Return>", self.toggle)
		self.canvas.bind("<Button-1>", self.focus_switch, add="+")
		self.variable.trace_add("write", self.refresh)
		self.refresh()

	def focus_switch(self, _event=None):
		self.canvas.focus_set()

	def toggle(self, _event=None):
		self.variable.set(not bool(self.variable.get()))
		if self.command:
			self.command()

	def refresh(self, *_args):
		self.canvas.delete("all")
		on = bool(self.variable.get())
		track = IOS_THEME["success"] if on else "#AEAEB2"
		self.canvas.create_oval(1, 1, self.HEIGHT - 1, self.HEIGHT - 1, fill=track, outline=track)
		self.canvas.create_rectangle(self.HEIGHT / 2, 1, self.WIDTH - self.HEIGHT / 2, self.HEIGHT - 1, fill=track, outline=track)
		self.canvas.create_oval(self.WIDTH - self.HEIGHT - 1, 1, self.WIDTH - 1, self.HEIGHT - 1, fill=track, outline=track)
		knob_x = self.WIDTH - self.KNOB - 2 if on else 2
		self.canvas.create_oval(knob_x, 3, knob_x + self.KNOB, 25, fill="#FFFFFF", outline="#D0D0D0")


class IOSButton(tk.Button):
	def __init__(self, parent, **kwargs):
		kwargs.setdefault("relief", "flat")
		kwargs.setdefault("bd", 0)
		kwargs.setdefault("bg", IOS_THEME["button"])
		kwargs.setdefault("fg", IOS_THEME["text"])
		kwargs.setdefault("activebackground", IOS_THEME["button_active"])
		kwargs.setdefault("activeforeground", "#FFFFFF")
		kwargs.setdefault("font", ("Segoe UI", 10))
		kwargs.setdefault("padx", 12)
		kwargs.setdefault("pady", 6)
		kwargs.setdefault("cursor", "hand2")
		super().__init__(parent, **kwargs)


class IOSPrimaryButton(IOSButton):
	def __init__(self, parent, **kwargs):
		kwargs.setdefault("bg", IOS_THEME["primary"])
		kwargs.setdefault("activebackground", IOS_THEME["primary_active"])
		kwargs.setdefault("font", ("Segoe UI", 10, "bold"))
		super().__init__(parent, **kwargs)


class IOSEntry(tk.Entry):
	def __init__(self, parent, **kwargs):
		kwargs.setdefault("relief", "flat")
		kwargs.setdefault("bd", 0)
		kwargs.setdefault("bg", IOS_THEME["field"])
		kwargs.setdefault("fg", IOS_THEME["text"])
		kwargs.setdefault("insertbackground", "#FFFFFF")
		kwargs.setdefault("highlightthickness", 1)
		kwargs.setdefault("highlightbackground", IOS_THEME["border"])
		kwargs.setdefault("highlightcolor", IOS_THEME["primary"])
		kwargs.setdefault("font", ("Segoe UI", 10))
		super().__init__(parent, **kwargs)


class IOSCombo(ttk.Combobox):
	def __init__(self, parent, **kwargs):
		kwargs.setdefault("style", "IOS.TCombobox")
		super().__init__(parent, **kwargs)


class IOSScrollbar(tk.Scrollbar):
	def __init__(self, parent, **kwargs):
		kwargs.setdefault("bg", IOS_THEME["button"])
		kwargs.setdefault("activebackground", "#5B7182")
		kwargs.setdefault("troughcolor", IOS_THEME["background"])
		kwargs.setdefault("bd", 0)
		kwargs.setdefault("width", 12)
		kwargs.setdefault("highlightthickness", 0)
		super().__init__(parent, **kwargs)


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
}

VISION_REGIONS = ("色框1 血量", "色框2 狀態", "色框3 地圖")
RULE_REGIONS = ("色框1 血量", "色框2 狀態")


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
			center = (image.size[0] / 2, image.size[1] / 2)
			if blue_points:
				closest_blue = min(blue_points, key=lambda point: self.distance(center, point))
				move_vector = (center[0] - closest_blue[0], center[1] - closest_blue[1])
				return {"direction": self.vector_direction(move_vector), "red_distance": None, "reason": "隨機移動時避開藍點"}
			return {"direction": random.choice(("left", "right", "up", "down")), "red_distance": None, "reason": "隨機移動"}
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
		self.app.set_status("執行中", "#34C759")
		while not self.stop_event.is_set():
			rules = sorted((rule for rule in self.app.rules if rule.enabled), key=lambda item: item.priority)
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
		self.app.set_status("已停止", "#FF9500")

	def run_navigation(self):
		while not self.stop_event.is_set():
			config = self.app.navigation_config
			if not config["enabled"]:
				self.stop_event.wait(0.1)
				continue
			decision = self.reader.navigation_decision("色框3 地圖", config["avoid_radius"])
			if decision:
				self.trigger_navigation_step(decision)
			else:
				self.app.log("導航：色框3 尚未偵測到紅點，暫停移動")
			self.stop_event.wait(0.08)

	def trigger_navigation_step(self, decision):
		config = self.app.navigation_config
		key = self.navigation_key(config["keys"], decision["direction"])
		self.app.log(f"導航更新：{decision['reason']} → {key}")
		if pyautogui is None:
			return
		self.app.focus_target()
		pyautogui.keyDown(key)
		self.stop_event.wait(config["hold"])
		pyautogui.keyUp(key)
		if config["roll"]:
			pyautogui.press("space")
		self.try_teleport(config)

	def try_teleport(self, config):
		if not config["teleport"] or pyautogui is None:
			return
		cooldown = config["teleport_cooldown"]
		if time.monotonic() - self.app.engine.last_teleport < cooldown:
			return
		key = config["teleport_key"]
		if not key:
			return
		self.app.focus_target()
		pyautogui.press(key)
		self.app.engine.last_teleport = time.monotonic()
		self.app.log(f"瞬移：{key}（冷卻 {cooldown:g}s）")

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
		return False

	def trigger(self, rule):
		self.last_run[rule.name] = time.time()
		key = rule.key
		self.app.log(f"觸發：{rule.name} → {key}")
		if pyautogui is None:
			self.app.log("預覽模式：尚未安裝 pyautogui，未送出按鍵")
			return
		self.send_rule_key_at_target(rule, key)

	def send_rule_key_at_target(self, rule, key):
		original_position = pyautogui.position()
		pressed = False
		try:
			self.app.focus_target()
			center = self.app.target_center()
			if center:
				pyautogui.moveTo(center[0], center[1], duration=0)
			pyautogui.keyDown(key)
			pressed = True
			time.sleep(max(0, rule.hold))
		finally:
			if pressed:
				pyautogui.keyUp(key)
			pyautogui.moveTo(original_position[0], original_position[1], duration=0)

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
		self.geometry("1280x780")
		self.minsize(1120, 680)
		self.configure(bg="#F2F2F7")
		self.rules = []
		self.regions = {}
		self.region_vars = {}
		self.status_icons = {}
		self.status_name_var = tk.StringVar()
		self.status_key_var = tk.StringVar()
		self.selected_rule_index = None
		self.drag_index = None
		self.resource_dir = Path(__file__).parent / "resources" / "status_icons"
		self.navigation_enabled = tk.BooleanVar(value=False)
		self.roll_enabled = tk.BooleanVar(value=False)
		self.teleport_enabled = tk.BooleanVar(value=False)
		self.teleport_key_var = tk.StringVar(value="e")
		self.teleport_cooldown_var = tk.StringVar(value="10")
		self.navigation_key_var = tk.StringVar(value="a,d,w,s")
		self.navigation_hold_var = tk.StringVar(value="0.12")
		self.navigation_avoid_radius_var = tk.StringVar(value="80")
		self.navigation_config = {}
		self.active_scroll_canvas = None
		self.theme_var = tk.StringVar(value="iOS 淺色")
		for variable in (self.navigation_enabled, self.roll_enabled, self.teleport_enabled, self.teleport_key_var, self.teleport_cooldown_var, self.navigation_key_var, self.navigation_hold_var, self.navigation_avoid_radius_var):
			variable.trace_add("write", lambda *_args: self.sync_navigation_config())
		self.sync_navigation_config()
		self.engine = AutomationEngine(self)
		self.protocol("WM_DELETE_WINDOW", self.close)
		self.build_style()
		self.build_ui()

	def build_style(self):
		style = ttk.Style(self)
		style.theme_use("clam")
		style.configure("TFrame", background="#F2F2F7")
		style.configure("Panel.TFrame", background="#FFFFFF")
		style.configure("TLabel", background="#FFFFFF", foreground="#1C1C1E", font=("Segoe UI", 10))
		style.configure("Title.TLabel", background="#F2F2F7", foreground="#1C1C1E", font=("Segoe UI", 22, "bold"))
		style.configure("Sub.TLabel", background="#F2F2F7", foreground="#8E8E93", font=("Segoe UI", 10))
		style.configure("TButton", background="#E5E5EA", foreground="#1C1C1E", padding=(12, 7), borderwidth=0)
		style.map("TButton", background=[("active", "#D1D1D6")])
		style.configure("IOS.TCombobox", fieldbackground="#FFFFFF", background="#E5E5EA", foreground="#1C1C1E", arrowcolor="#007AFF", borderwidth=0, padding=6)
		style.map("IOS.TCombobox", fieldbackground=[("readonly", "#FFFFFF")], foreground=[("readonly", "#1C1C1E")])
		style.configure("Accent.TButton", background="#007AFF", foreground="white", font=("Segoe UI", 10, "bold"))
		style.map("Accent.TButton", background=[("active", "#5AC8FA")])
		style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#1C1C1E", rowheight=32, borderwidth=0)
		style.configure("Treeview.Heading", background="#E5E5EA", foreground="#636366", relief="flat")

	def apply_theme(self, theme):
		IOS_THEME.update(theme)
		self.configure(bg=IOS_THEME["background"])
		style = ttk.Style(self)
		style.configure("TFrame", background=IOS_THEME["background"])
		style.configure("Panel.TFrame", background=IOS_THEME["panel"])
		style.configure("TLabel", background=IOS_THEME["panel"], foreground=IOS_THEME["text"])
		style.configure("Title.TLabel", background=IOS_THEME["background"], foreground=IOS_THEME["text"])
		style.configure("Sub.TLabel", background=IOS_THEME["background"], foreground=IOS_THEME["muted"])
		style.configure("IOS.TCombobox", fieldbackground=IOS_THEME["field"], background=IOS_THEME["button"], foreground=IOS_THEME["text"], arrowcolor=IOS_THEME["primary"])
		style.configure("TButton", background=IOS_THEME["button"], foreground=IOS_THEME["text"])
		style.configure("Accent.TButton", background=IOS_THEME["primary"], foreground="white")
		self.refresh_theme_widgets(self)

	def refresh_theme_widgets(self, parent):
		for widget in parent.winfo_children():
			if isinstance(widget, IOSSwitch):
				try:
					background = widget.master.cget("background")
				except tk.TclError:
					background = IOS_THEME["panel"]
				widget.configure(bg=background)
				widget.canvas.configure(bg=background)
				widget.refresh()
			elif isinstance(widget, IOSPrimaryButton):
				widget.configure(bg=IOS_THEME["primary"], activebackground=IOS_THEME["primary_active"])
			elif isinstance(widget, IOSButton):
				widget.configure(bg=IOS_THEME["button"], fg=IOS_THEME["text"], activebackground=IOS_THEME["button_active"])
			elif isinstance(widget, IOSEntry):
				widget.configure(bg=IOS_THEME["field"], fg=IOS_THEME["text"], highlightbackground=IOS_THEME["border"], highlightcolor=IOS_THEME["primary"])
			elif isinstance(widget, IOSScrollbar):
				widget.configure(bg=IOS_THEME["button"], activebackground=IOS_THEME["primary_active"], troughcolor=IOS_THEME["background"])
			elif isinstance(widget, tk.Canvas):
				widget.configure(bg=IOS_THEME["panel"])
			elif isinstance(widget, tk.Frame):
				widget.configure(bg=IOS_THEME["card"])
			elif isinstance(widget, tk.Label):
				try:
					widget.configure(bg=widget.master.cget("background"), fg=IOS_THEME["text"])
				except tk.TclError:
					widget.configure(fg=IOS_THEME["text"])
			self.refresh_theme_widgets(widget)

	def choose_theme(self, _event=None):
		name = self.theme_var.get()
		if name in THEME_PRESETS:
			self.apply_theme(THEME_PRESETS[name])

	def choose_custom_color(self, key):
		color = colorchooser.askcolor(color=IOS_THEME[key], title="選擇主題色")[1]
		if color:
			IOS_THEME[key] = color.upper()
			self.theme_var.set("自訂")
			self.apply_theme(IOS_THEME)

	def build_ui(self):
		header = ttk.Frame(self)
		header.pack(fill="x", padx=28, pady=(24, 14))
		ttk.Label(header, text="AUTOKEY CONTROL", style="Title.TLabel").pack(anchor="w")
		ttk.Label(header, text="用視覺條件驅動按鍵規則，讓長時間操作保持可控、可追蹤。", style="Sub.TLabel").pack(anchor="w", pady=(3, 0))

		toolbar = ttk.Frame(self)
		toolbar.pack(fill="x", padx=28, pady=(0, 14))
		ttk.Label(toolbar, text="目標視窗標題").pack(side="left")
		self.target_var = tk.StringVar()
		IOSEntry(toolbar, textvariable=self.target_var, width=28).pack(side="left", padx=(10, 8))
		IOSButton(toolbar, text="重新整理視窗", command=self.refresh_windows).pack(side="left")
		self.window_var = tk.StringVar(value="尚未選擇")
		self.window_combo = IOSCombo(toolbar, textvariable=self.window_var, state="readonly", width=32)
		self.window_combo.pack(side="left", padx=8)
		self.window_combo.bind("<<ComboboxSelected>>", self.on_window_selected)
		toolbar_actions = ttk.Frame(toolbar)
		toolbar_actions.pack(side="right", padx=(16, 0))
		self.theme_combo = IOSCombo(toolbar_actions, textvariable=self.theme_var, state="readonly", values=tuple(THEME_PRESETS) + ("自訂",), width=12)
		self.theme_combo.pack(side="left", padx=(0, 8))
		IOSButton(toolbar_actions, text="自訂主色", command=lambda: self.choose_custom_color("primary")).pack(side="left", padx=(0, 8))
		IOSButton(toolbar_actions, text="自訂背景色", command=lambda: self.choose_custom_color("background")).pack(side="left", padx=(0, 8))
		IOSButton(toolbar_actions, text="載入設定", command=self.load).pack(side="left", padx=(0, 8))
		IOSButton(toolbar_actions, text="儲存設定", command=self.save).pack(side="left")
		self.theme_combo.bind("<<ComboboxSelected>>", self.choose_theme)

		body = ttk.Panedwindow(self, orient="horizontal")
		body.pack(fill="both", expand=True, padx=28, pady=(0, 20))
		left = ttk.Frame(body, style="Panel.TFrame", padding=16)
		right_shell = ttk.Frame(body, style="Panel.TFrame")
		body.add(left, weight=3)
		body.add(right_shell, weight=2)
		right_shell.grid_rowconfigure(0, weight=1)
		right_shell.grid_columnconfigure(0, weight=1)
		right_canvas = tk.Canvas(right_shell, bg="#FFFFFF", highlightthickness=0)
		right_scroll = IOSScrollbar(right_shell, orient="vertical", command=right_canvas.yview)
		right_canvas.configure(yscrollcommand=right_scroll.set)
		right_canvas.grid(row=0, column=0, sticky="nsew")
		right_scroll.grid(row=0, column=1, sticky="ns")
		right = ttk.Frame(right_canvas, style="Panel.TFrame", padding=16)
		right_window = right_canvas.create_window((0, 0), window=right, anchor="nw")
		right.bind("<Configure>", lambda _event: right_canvas.configure(scrollregion=right_canvas.bbox("all")))
		right_canvas.bind("<Configure>", lambda event: right_canvas.itemconfigure(right_window, width=event.width))
		right_canvas.bind("<Enter>", lambda _event: self.set_scroll_canvas(right_canvas))
		ttk.Label(left, text="規則優先序", font=("Segoe UI", 13, "bold")).pack(anchor="w")
		ttk.Label(left, text="卡片由上到下執行；使用上移 / 下移調整優先順序。", foreground="#8E8E93").pack(anchor="w", pady=(3, 12))
		cards_shell = ttk.Frame(left, style="Panel.TFrame")
		cards_shell.pack(fill="both", expand=True)
		cards_canvas = tk.Canvas(cards_shell, bg="#FFFFFF", highlightthickness=0)
		cards_scroll = IOSScrollbar(cards_shell, orient="vertical", command=cards_canvas.yview)
		cards_canvas.configure(yscrollcommand=cards_scroll.set)
		cards_canvas.pack(side="left", fill="both", expand=True)
		cards_scroll.pack(side="right", fill="y")
		self.cards_frame = ttk.Frame(cards_canvas, style="Panel.TFrame")
		cards_window = cards_canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
		self.cards_frame.bind("<Configure>", lambda _event: cards_canvas.configure(scrollregion=cards_canvas.bbox("all")))
		cards_canvas.bind("<Configure>", lambda event: cards_canvas.itemconfigure(cards_window, width=event.width))
		cards_canvas.bind("<Enter>", lambda _event: self.set_scroll_canvas(cards_canvas))
		self.bind_all("<MouseWheel>", self.scroll_active_panel)
		actions = ttk.Frame(left)
		actions.pack(fill="x", pady=(12, 0))
		IOSButton(actions, text="新增規則", command=self.new_rule).pack(side="left")
		IOSButton(actions, text="套用編輯", command=self.update_rule).pack(side="left", padx=8)
		IOSButton(actions, text="刪除規則", command=self.delete_rule).pack(side="left")

		ttk.Label(right, text="規則編輯器", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
		self.fields = {}
		self.field_widgets = {}
		self.action_label = None
		field_defs = [("name", "名稱"), ("priority", "優先度"), ("condition", "條件"), ("value", "數值 / 門檻"), ("key", "施放按鍵"), ("hold", "按住秒數"), ("cooldown", "冷卻秒數"), ("region", "判斷色框"), ("icon", "圖示資源")]
		for row, (key, label) in enumerate(field_defs, 1):
			if key == "key":
				self.action_label = ttk.Label(right, text=label)
				self.action_label.grid(row=row, column=0, sticky="w", pady=6)
			else:
				ttk.Label(right, text=label).grid(row=row, column=0, sticky="w", pady=6)
			variable = tk.StringVar()
			self.fields[key] = variable
			if key == "name":
				name_field = ttk.Frame(right)
				name_field.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=6)
				widget = IOSEntry(name_field, textvariable=variable, width=15)
				widget.pack(side="left")
				self.enabled_var = tk.BooleanVar(value=True)
				IOSSwitch(name_field, self.enabled_var).pack(side="left", padx=(12, 0), pady=1)
			elif key == "condition":
				widget = IOSCombo(right, textvariable=variable, state="readonly", values=list(CONDITIONS.values()), width=22)
				widget.bind("<<ComboboxSelected>>", self.on_condition_change)
			elif key == "region":
				widget = IOSCombo(right, textvariable=variable, state="readonly", values=RULE_REGIONS, width=22)
			elif key == "icon":
				widget = IOSCombo(right, textvariable=variable, state="readonly", values=(), width=22)
			else:
				widget = IOSEntry(right, textvariable=variable, width=25)
			if key != "name":
				widget.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=6)
			self.field_widgets[key] = widget
		ttk.Separator(right).grid(row=10, column=0, columnspan=2, sticky="ew", pady=5)
		tk.Label(right, text="色框3已移至下方獨立控制，不列入規則優先序", foreground="#8E8E93").grid(row=10, column=1, sticky="w", pady=(0, 5))
		ttk.Label(right, text="視覺區域（相對目標視窗）", font=("Segoe UI", 11, "bold")).grid(row=11, column=0, columnspan=2, sticky="w", pady=(14, 8))
		for row, region in enumerate(("色框1 血量", "色框2 狀態", "色框3 地圖"), 12):
			ttk.Label(right, text=region).grid(row=row, column=0, sticky="w", pady=5)
			variable = tk.StringVar()
			self.region_vars[region] = variable
			field = ttk.Frame(right)
			field.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=5)
			IOSEntry(field, textvariable=variable, width=17).pack(side="left")
			IOSButton(field, text="框選", command=lambda name=region: self.select_region(name)).pack(side="left", padx=(5, 0))
		tk.Label(right, text="格式：相對 x,y,width,height", foreground="#8E8E93").grid(row=15, column=1, sticky="w", pady=(2, 14))
		ttk.Label(right, text="色框2 狀態圖示（每行一個）", font=("Segoe UI", 11, "bold")).grid(row=16, column=0, columnspan=2, sticky="w", pady=(4, 6))
		tk.Label(right, text="色框3 獨立移動控制", font=("Segoe UI", 11, "bold")).grid(row=20, column=0, columnspan=2, sticky="w", pady=(4, 8))
		navigation_toggle = ttk.Frame(right)
		navigation_toggle.grid(row=21, column=0, columnspan=2, sticky="w", pady=4)
		ttk.Label(navigation_toggle, text="啟用色框3隨機移動 / 紅點導航").pack(side="left")
		IOSSwitch(navigation_toggle, self.navigation_enabled).pack(side="left", padx=(14, 0), pady=1)
		tk.Label(right, text="移動按鍵（左,右,上,下）").grid(row=22, column=0, sticky="w", pady=4)
		IOSEntry(right, textvariable=self.navigation_key_var, width=25).grid(row=22, column=1, sticky="ew", padx=(14, 0), pady=4)
		tk.Label(right, text="藍點避讓距離").grid(row=23, column=0, sticky="w", pady=4)
		IOSEntry(right, textvariable=self.navigation_avoid_radius_var, width=25).grid(row=23, column=1, sticky="ew", padx=(14, 0), pady=4)
		tk.Label(right, text="移動按住秒數").grid(row=24, column=0, sticky="w", pady=4)
		IOSEntry(right, textvariable=self.navigation_hold_var, width=25).grid(row=24, column=1, sticky="ew", padx=(14, 0), pady=4)
		roll_toggle = ttk.Frame(right)
		roll_toggle.grid(row=25, column=0, columnspan=2, sticky="w", pady=4)
		ttk.Label(roll_toggle, text="移動後使用空白鍵翻滾").pack(side="left")
		IOSSwitch(roll_toggle, self.roll_enabled).pack(side="left", padx=(14, 0), pady=1)
		teleport_toggle = ttk.Frame(right)
		teleport_toggle.grid(row=26, column=0, columnspan=2, sticky="w", pady=4)
		ttk.Label(teleport_toggle, text="啟用瞬移技能").pack(side="left")
		IOSSwitch(teleport_toggle, self.teleport_enabled).pack(side="left", padx=(14, 0), pady=1)
		tk.Label(right, text="瞬移按鍵").grid(row=27, column=0, sticky="w", pady=4)
		IOSEntry(right, textvariable=self.teleport_key_var, width=25).grid(row=27, column=1, sticky="ew", padx=(14, 0), pady=4)
		tk.Label(right, text="瞬移最小間隔（秒）").grid(row=28, column=0, sticky="w", pady=4)
		IOSEntry(right, textvariable=self.teleport_cooldown_var, width=25).grid(row=28, column=1, sticky="ew", padx=(14, 0), pady=4)
		status_toolbar = ttk.Frame(right)
		status_toolbar.grid(row=17, column=0, columnspan=2, sticky="ew", pady=(0, 5))
		IOSEntry(status_toolbar, textvariable=self.status_name_var, width=15).pack(side="left")
		IOSEntry(status_toolbar, textvariable=self.status_key_var, width=8).pack(side="left", padx=(6, 0))
		IOSButton(status_toolbar, text="框選並加入", command=self.select_status_icon).pack(side="left", padx=(5, 0))
		self.status_text = tk.Text(right, height=4, width=35, bg="#FFFFFF", fg="#1C1C1E", insertbackground="#007AFF", relief="flat", highlightthickness=1, highlightbackground="#D1D1D6")
		self.status_text.grid(row=18, column=0, columnspan=2, sticky="ew")
		tk.Label(right, text="上方依序輸入：狀態名稱、缺少時施放按鍵；框選後會保存為該狀態資源", foreground="#8E8E93", wraplength=270).grid(row=19, column=0, columnspan=2, sticky="w", pady=(4, 12))

		footer = ttk.Frame(self)
		footer.pack(fill="x", padx=28, pady=(0, 20))
		self.status_label = ttk.Label(footer, text="●  待命", foreground="#FF9500")
		self.status_label.pack(side="left")
		self.log_text = tk.Text(footer, height=4, bg="#FFFFFF", fg="#636366", insertbackground="#007AFF", relief="flat", highlightthickness=1, highlightbackground="#D1D1D6", state="disabled")
		self.log_text.pack(side="left", fill="x", expand=True, padx=22)
		IOSPrimaryButton(footer, text="開始執行", command=self.start).pack(side="right")
		IOSButton(footer, text="停止", command=self.stop).pack(side="right", padx=8)
		self.sample_rules()

	def set_scroll_canvas(self, canvas):
		self.active_scroll_canvas = canvas

	def scroll_active_panel(self, event):
		if self.active_scroll_canvas is not None:
			self.active_scroll_canvas.yview_scroll(int(-event.delta / 120), "units")

	def sample_rules(self):
		self.rules = [Rule("低血量保命", True, 1, "hp_below", "35", "F1", 0.12, 3.0, "色框1 血量"), Rule("補上狀態", True, 2, "status_missing", "0.8", "2", 0.15, 8.0, "色框2 狀態", "護盾"), Rule("週期技能", True, 3, "interval", "5", "3", 0.1, 5.0, "色框1 血量")]
		self.refresh_tree()
		self.log("已載入範例規則；視覺區域需依遊戲畫面填入座標。")

	def refresh_tree(self):
		for child in self.cards_frame.winfo_children():
			child.destroy()
		for index, rule in enumerate(self.rules):
			card = tk.Frame(self.cards_frame, bg=IOS_THEME["card"], highlightthickness=2, highlightbackground=IOS_THEME["border"], padx=14, pady=10)
			card.pack(fill="x", pady=(0, 12))
			card.bind("<Button-1>", lambda _event, value=index: self.select_rule(value))
			card.bind("<ButtonPress-1>", lambda _event, value=index: self.begin_drag(value))
			card.bind("<ButtonRelease-1>", self.finish_drag)
			condition = CONDITIONS.get(rule.condition, rule.condition)
			tk.Label(card, text=f"{index + 1:02d}  {rule.name}", background=IOS_THEME["card"], foreground=IOS_THEME["text"], font=("Segoe UI", 11, "bold")).pack(side="left")
			tk.Label(card, text=condition, background=IOS_THEME["card"], foreground=IOS_THEME["secondary"]).pack(side="left", padx=12)
			tk.Label(card, text=f"按鍵 {rule.key}  冷卻 {rule.cooldown}s", background=IOS_THEME["card"], foreground=IOS_THEME["secondary"]).pack(side="left")
			enabled_var = tk.BooleanVar(value=rule.enabled)
			IOSSwitch(card, enabled_var, command=lambda value=index, variable=enabled_var: self.toggle_rule(value, variable.get())).pack(side="right", padx=(0, 24), pady=2)
			IOSButton(card, text="上移", command=lambda value=index: self.move_rule(value, -1)).pack(side="right", padx=(0, 14), pady=2)
			IOSButton(card, text="下移", command=lambda value=index: self.move_rule(value, 1)).pack(side="right", padx=(0, 14), pady=2)
			for child in card.winfo_children():
				if isinstance(child, tk.Label):
					child.bind("<Button-1>", lambda _event, value=index: self.select_rule(value))
					child.bind("<ButtonPress-1>", lambda _event, value=index: self.begin_drag(value))
					child.bind("<ButtonRelease-1>", self.finish_drag)
			if index == self.selected_rule_index:
				card.configure(highlightbackground=IOS_THEME["primary"])

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
		if rule.condition == "status_missing" and rule.icon in self.status_icons:
			self.fields["key"].set(self.status_icons[rule.icon].get("apply_key", rule.key))
		self.enabled_var.set(rule.enabled)
		self.field_widgets["icon"]["values"] = tuple(self.status_icons.keys())
		self.update_action_label(rule.condition)

	def on_condition_change(self, _event=None):
		condition_label = self.fields["condition"].get()
		condition = next((key for key, label in CONDITIONS.items() if label == condition_label), condition_label)
		self.update_action_label(condition)

	def update_action_label(self, condition):
		if self.action_label is None:
			return
		text = "缺少狀態時施放按鍵" if condition == "status_missing" else "施放按鍵"
		self.action_label.configure(text=text)

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
			icon_data = self.status_icons.get(rule.icon, {})
			rule.icon_path = str(icon_data.get("path", ""))
			if rule.condition == "status_missing" and rule.icon in self.status_icons:
				self.status_icons[rule.icon]["apply_key"] = rule.key
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
				parts = data.split("|", 2)
				coordinate_text = parts[0]
				path = parts[1] if len(parts) > 1 else ""
				apply_key = parts[2].strip() if len(parts) > 2 else ""
				values = tuple(int(item.strip()) for item in coordinate_text.split(","))
				if name.strip() and len(values) == 4:
					result[name.strip()] = {"region": values, "path": path.strip(), "apply_key": apply_key}
			except ValueError:
				continue
		self.status_icons = result

	def start(self):
		self.parse_regions()
		self.parse_status_icons()
		self.sync_navigation_config()
		if not self.rules and not self.navigation_enabled.get():
			messagebox.showinfo("提示", "請先新增規則或啟用色框3移動。")
			return
		self.engine.start()

	def sync_navigation_config(self):
		try:
			hold = max(0.02, float(self.navigation_hold_var.get()))
		except ValueError:
			hold = 0.12
		try:
			avoid_radius = max(1.0, float(self.navigation_avoid_radius_var.get()))
		except ValueError:
			avoid_radius = 80.0
		try:
			teleport_cooldown = max(0.1, float(self.teleport_cooldown_var.get()))
		except ValueError:
			teleport_cooldown = 10.0
		self.navigation_config = {"enabled": bool(self.navigation_enabled.get()), "roll": bool(self.roll_enabled.get()), "teleport": bool(self.teleport_enabled.get()), "keys": self.navigation_key_var.get().strip() or "a,d,w,s", "hold": hold, "avoid_radius": avoid_radius, "teleport_key": self.teleport_key_var.get().strip(), "teleport_cooldown": teleport_cooldown}

	def navigation_hold(self):
		try:
			return max(0.02, float(self.navigation_hold_var.get()))
		except ValueError:
			return 0.12

	def navigation_avoid_radius(self):
		try:
			return max(1.0, float(self.navigation_avoid_radius_var.get()))
		except ValueError:
			return 80.0

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

	def target_center(self):
		bounds = self.target_bounds()
		if not bounds:
			return None
		left, top, width, height = bounds
		return left + width // 2, top + height // 2

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
			apply_key = self.status_key_var.get().strip()
			if not apply_key:
				messagebox.showinfo("需要施放按鍵", "請輸入此狀態缺少時要施放的按鍵。")
				return
			lines = []
			for line in self.status_text.get("1.0", "end").splitlines():
				if "=" in line and line.split("=", 1)[0].strip() != name:
					lines.append(line)
			lines.append(f"{name}={','.join(map(str, region))}|{path}|{apply_key}")
			self.status_text.delete("1.0", "end")
			self.status_text.insert("1.0", "\n".join(lines))
			self.status_name_var.set("")
			self.status_key_var.set("")

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
		data = {"target": self.target_var.get(), "window": self.window_var.get(), "theme": IOS_THEME, "regions": self.regions, "status_icons": self.status_icons, "rules": [asdict(rule) for rule in self.rules], "navigation": {"enabled": self.navigation_enabled.get(), "keys": self.navigation_key_var.get(), "hold": self.navigation_hold_var.get(), "avoid_radius": self.navigation_avoid_radius_var.get(), "roll": self.roll_enabled.get(), "teleport": self.teleport_enabled.get(), "teleport_key": self.teleport_key_var.get(), "teleport_cooldown": self.teleport_cooldown_var.get()}}
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
			if isinstance(data.get("theme"), dict):
				IOS_THEME.update({key: str(value) for key, value in data["theme"].items() if key in IOS_THEME})
				self.theme_var.set("自訂")
				self.apply_theme(IOS_THEME)
			navigation = data.get("navigation", {})
			self.navigation_enabled.set(bool(navigation.get("enabled", False)))
			self.navigation_key_var.set(str(navigation.get("keys", "a,d,w,s")))
			self.navigation_hold_var.set(str(navigation.get("hold", "0.12")))
			self.navigation_avoid_radius_var.set(str(navigation.get("avoid_radius", "80")))
			self.roll_enabled.set(bool(navigation.get("roll", False)))
			self.teleport_enabled.set(bool(navigation.get("teleport", False)))
			self.teleport_key_var.set(str(navigation.get("teleport_key", "e")))
			self.teleport_cooldown_var.set(str(navigation.get("teleport_cooldown", "10")))
			for key, value in data.get("regions", {}).items():
				self.region_vars.setdefault(key, tk.StringVar()).set(",".join(map(str, value)))
			for region in ("色框1 血量", "色框2 狀態", "色框3 地圖"):
				self.region_vars.setdefault(region, tk.StringVar())
			self.regions = {key: tuple(value) for key, value in data.get("regions", {}).items()}
			self.status_icons = {}
			for key, value in data.get("status_icons", {}).items():
				if isinstance(value, dict):
					self.status_icons[key] = {**value, "apply_key": value.get("apply_key", "")}
				else:
					self.status_icons[key] = {"region": tuple(value), "path": "", "apply_key": ""}
			self.status_text.delete("1.0", "end")
			self.status_text.insert("1.0", "\n".join(f"{key}={','.join(map(str, value.get('region', ())))}|{value.get('path', '')}|{value.get('apply_key', '')}" for key, value in self.status_icons.items()))
			self.rules = []
			for item in data.get("rules", []):
				item = dict(item)
				if item.get("condition") == "red_dot_navigation":
					continue
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
