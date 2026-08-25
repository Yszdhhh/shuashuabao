"""UIAutomationCore 的纯 ctypes 后端（零第三方依赖）。

实证结论（2026-08-11 本机验证）：
- 可用：CoCreateInstance / GetRootElement / ElementFromHandle /
  FindAll(Children, TrueCondition) / GetCurrentPropertyValue /
  GetCurrentPattern（Invoke/Value/Toggle）。
- 不可用：CreatePropertyCondition（VARIANT 按值传参会触发
  access violation，ctypes x64 ABI 限制）——因此本后端一律用
  FindAll(TrueCondition) 快照 + Python 侧 selector 过滤，不调用该方法。
- FindAll 对个别元素可能返回 E_FAIL（桌面 shell 元素）；一律按叶子处理。

所有原生调用都做 try/except 兜底（ctypes 对负 HRESULT 会抛 OSError），
任何失败返回 None/[]，绝不向上抛 —— Fail-Closed 语义由 adapter 负责。

后端非线程安全：单线程使用（与 mediator tick 循环一致）。
"""

from __future__ import annotations

import ctypes
import re
import struct
from ctypes import HRESULT, POINTER, Structure, WINFUNCTYPE, byref, c_void_p, c_ulong, c_ushort, c_ubyte, c_int, c_uint
from ctypes import wintypes

from .source import (
    PROP_AUTOMATION_ID,
    PROP_CLASS_NAME,
    PROP_CONTROL_TYPE,
    PROP_FRAMEWORK_ID,
    PROP_NAME,
    PROP_PROCESS_ID,
)

S_OK = 0
CLSCTX_INPROC_SERVER = 0x1
VT_EMPTY = 0
VT_I4 = 3
VT_BSTR = 8

CLSID_CUIAutomation = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"
IID_IUIAutomation = "{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}"

TreeScope_Children = 0x2

# UIAutomationCore.dll 缺失/不可加载时后端不可用（旧系统、精简环境）
_UIAUTOMATION_DLL = "UIAutomationCore.dll"

_ole32 = None
_oleaut32 = None
_uiauto_dll = None


def _load_apis() -> bool:
    """惰性加载 ole32/oleaut32/UIAutomationCore；失败返回 False。"""
    global _ole32, _oleaut32, _uiauto_dll
    if _ole32 is not None:
        return _uiauto_dll is not None
    try:
        import ctypes.wintypes  # noqa: F401  (确保 wintypes 已注册)

        _ole32 = ctypes.windll.ole32
        _oleaut32 = ctypes.windll.oleaut32
        _oleaut32.SysAllocString.argtypes = [wintypes.LPCWSTR]
        _oleaut32.SysAllocString.restype = c_void_p
        _oleaut32.SysFreeString.argtypes = [c_void_p]
        _oleaut32.SysFreeString.restype = None
        _uiauto_dll = ctypes.WinDLL(_UIAUTOMATION_DLL)
        return True
    except Exception:
        _ole32 = ctypes.windll.ole32  # 标记已尝试
        _oleaut32 = ctypes.windll.oleaut32
        _uiauto_dll = None
        return False


class _GUID(Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _parse_guid(text: str) -> _GUID:
    m = re.fullmatch(
        r"\{?([0-9A-Fa-f]{8})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{12})\}?",
        text,
    )
    if not m:
        raise ValueError(f"bad guid {text!r}")
    return _GUID(
        int(m.group(1), 16),
        int(m.group(2), 16),
        int(m.group(3), 16),
        (ctypes.c_ubyte * 8)(*bytes.fromhex(m.group(4) + m.group(5))),
    )


_QI = WINFUNCTYPE(HRESULT, c_void_p, POINTER(_GUID), POINTER(c_void_p))
_AR = WINFUNCTYPE(c_ulong, c_void_p)
_RL = WINFUNCTYPE(c_ulong, c_void_p)


def _vtable(fields: list, tail: int) -> type:
    """构造 vtable Structure：前段具名方法 + 尾段占位（对齐后续槽位）。"""
    padded = list(fields) + [(f"_slot{i}", c_void_p) for i in range(tail)]
    return type("Vtbl", (Structure,), {"_fields_": padded})


# IUIAutomation：只用到 5(GetRootElement)/6(ElementFromHandle)/20(CreateTrueCondition)
_UIA_VTBL = _vtable(
    [
        ("QueryInterface", _QI),
        ("AddRef", _AR),
        ("Release", _RL),
        ("CompareElements", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, c_void_p, POINTER(c_int))),
        ("CompareRuntimeIds", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, c_void_p, POINTER(c_int))),
        ("GetRootElement", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("ElementFromHandle", WINFUNCTYPE(HRESULT, c_void_p, wintypes.HWND, POINTER(c_void_p))),
        ("ElementFromPoint", WINFUNCTYPE(HRESULT, c_void_p, wintypes.POINT, POINTER(c_void_p))),
        ("GetFocusedElement", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("GetRootElementBuildCache", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_void_p))),
        ("ElementFromHandleBuildCache", WINFUNCTYPE(HRESULT, c_void_p, wintypes.HWND, c_void_p, POINTER(c_void_p))),
        ("ElementFromPointBuildCache", WINFUNCTYPE(HRESULT, c_void_p, wintypes.POINT, c_void_p, POINTER(c_void_p))),
        ("GetFocusedElementBuildCache", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_void_p))),
        ("CreateTreeWalker", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_void_p))),
        ("ControlViewWalker_get", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("ContentViewWalker_get", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("RawViewWalker_get", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("RawViewCondition_get", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("ControlViewCondition_get", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("ContentViewCondition_get", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("CreateTrueCondition", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("CreateFalseCondition", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("CreatePropertyCondition", WINFUNCTYPE(HRESULT, c_void_p, c_int, c_ubyte * 16, POINTER(c_void_p))),
        ("CreatePropertyConditionEx", WINFUNCTYPE(HRESULT, c_void_p, c_int, c_ubyte * 16, c_uint, POINTER(c_void_p))),
        ("CreateAndCondition", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, c_void_p, POINTER(c_void_p))),
        ("CreateOrCondition", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, c_void_p, POINTER(c_void_p))),
        ("CreateNotCondition", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_void_p))),
    ],
    tail=60 - 27,
)


class _IUIAutomation(Structure):
    _fields_ = [("lpVtbl", POINTER(_UIA_VTBL))]


# IUIAutomationElement：6(FindAll)/10(GetCurrentPropertyValue)/16(GetCurrentPattern)
_ELEM_VTBL = _vtable(
    [
        ("QueryInterface", _QI),
        ("AddRef", _AR),
        ("Release", _RL),
        ("SetFocus", WINFUNCTYPE(HRESULT, c_void_p)),
        ("GetRuntimeId", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("FindFirst", WINFUNCTYPE(HRESULT, c_void_p, c_uint, c_void_p, POINTER(c_void_p))),
        ("FindAll", WINFUNCTYPE(HRESULT, c_void_p, c_uint, c_void_p, POINTER(c_void_p))),
        ("FindFirstBuildCache", WINFUNCTYPE(HRESULT, c_void_p, c_uint, c_void_p, c_void_p, POINTER(c_void_p))),
        ("FindAllBuildCache", WINFUNCTYPE(HRESULT, c_void_p, c_uint, c_void_p, c_void_p, POINTER(c_void_p))),
        ("BuildUpdatedCache", WINFUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_void_p))),
        ("GetCurrentPropertyValue", WINFUNCTYPE(HRESULT, c_void_p, c_int, POINTER(c_ubyte * 16))),
        ("GetCurrentPropertyValueEx", WINFUNCTYPE(HRESULT, c_void_p, c_int, c_int, POINTER(c_ubyte * 16))),
        ("GetCachedPropertyValue", WINFUNCTYPE(HRESULT, c_void_p, c_int, POINTER(c_ubyte * 16))),
        ("GetCachedPropertyValueEx", WINFUNCTYPE(HRESULT, c_void_p, c_int, c_int, POINTER(c_ubyte * 16))),
        ("GetCurrentPatternAs", WINFUNCTYPE(HRESULT, c_void_p, c_int, POINTER(_GUID), POINTER(c_void_p))),
        ("GetCachedPatternAs", WINFUNCTYPE(HRESULT, c_void_p, c_int, POINTER(_GUID), POINTER(c_void_p))),
        ("GetCurrentPattern", WINFUNCTYPE(HRESULT, c_void_p, c_int, POINTER(c_void_p))),
        ("GetCachedPattern", WINFUNCTYPE(HRESULT, c_void_p, c_int, POINTER(c_void_p))),
        ("GetCachedParent", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("GetCachedChildren", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("get_CurrentProcessId", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentControlType", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsEnabled", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentBoundingRectangle", WINFUNCTYPE(HRESULT, c_void_p, POINTER(wintypes.RECT))),
        ("get_CurrentName", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("get_CurrentAcceleratorKey", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("get_CurrentAccessKey", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("get_CurrentHasKeyboardFocus", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsKeyboardFocusable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsSelected", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsOffscreen", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentOrientation", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentFrameworkId", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("get_CurrentIsRequiredForForm", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentItemStatus", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("get_CurrentIsDockPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsExpandCollapsePatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsGridItemPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsGridPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsInvokePatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsMultipleViewPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsRangeValuePatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsScrollPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsScrollItemPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsSelectionItemPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsSelectionPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsTablePatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsTableItemPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsTextPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsTogglePatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsTransformPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsValuePatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_CurrentIsWindowPatternAvailable", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
    ],
    tail=120 - 53,
)


class _IUIAutomationElement(Structure):
    _fields_ = [("lpVtbl", POINTER(_ELEM_VTBL))]


_ARR_VTBL = _vtable(
    [
        ("QueryInterface", _QI),
        ("AddRef", _AR),
        ("Release", _RL),
        ("get_Length", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
        ("get_Element", WINFUNCTYPE(HRESULT, c_void_p, c_int, POINTER(c_void_p))),
    ],
    tail=0,
)


class _IUIAutomationElementArray(Structure):
    _fields_ = [("lpVtbl", POINTER(_ARR_VTBL))]


_INV_VTBL = _vtable(
    [
        ("QueryInterface", _QI),
        ("AddRef", _AR),
        ("Release", _RL),
        ("Invoke", WINFUNCTYPE(HRESULT, c_void_p)),
    ],
    tail=0,
)


class _IUIAutomationInvokePattern(Structure):
    _fields_ = [("lpVtbl", POINTER(_INV_VTBL))]


_VAL_VTBL = _vtable(
    [
        ("QueryInterface", _QI),
        ("AddRef", _AR),
        ("Release", _RL),
        ("SetValue", WINFUNCTYPE(HRESULT, c_void_p, c_void_p)),
        ("get_CurrentValue", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_void_p))),
        ("get_CurrentIsReadOnly", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
    ],
    tail=0,
)


class _IUIAutomationValuePattern(Structure):
    _fields_ = [("lpVtbl", POINTER(_VAL_VTBL))]


_TOG_VTBL = _vtable(
    [
        ("QueryInterface", _QI),
        ("AddRef", _AR),
        ("Release", _RL),
        ("Toggle", WINFUNCTYPE(HRESULT, c_void_p)),
        ("get_CurrentToggleState", WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_int))),
    ],
    tail=0,
)


class _IUIAutomationTogglePattern(Structure):
    _fields_ = [("lpVtbl", POINTER(_TOG_VTBL))]


class _IUnknown(Structure):
    _fields_ = [("lpVtbl", POINTER(c_void_p))]


def _release(ptr: int | c_void_p | None) -> None:
    if not ptr:
        return
    value = ptr.value if isinstance(ptr, c_void_p) else ptr
    if not value:
        return
    try:
        ctypes.cast(value, POINTER(_IUnknown)).contents.lpVtbl[2](value)
    except Exception:
        pass


def _as_uintptr(v: c_void_p) -> int:
    return v.value or 0


class CtypesUiaBackend:
    """纯 ctypes 的 UIAutomationCore 后端（实现 ElementSource 协议）。"""

    def __init__(self) -> None:
        self._uia: c_void_p | None = None
        self._true_condition: c_void_p | None = None
        self._coinit_hr: int | None = None
        self._closed = False
        self._error: str | None = None

    # ---- 生命周期 ----

    def is_available(self) -> bool:
        return self._ensure() is not None

    def describe(self) -> str:
        return f"ctypes:{_UIAUTOMATION_DLL}"

    def _ensure(self) -> _IUIAutomation | None:
        if self._closed:
            return None
        if self._uia is not None:
            return ctypes.cast(self._uia, POINTER(_IUIAutomation))
        if not _load_apis():
            self._error = "UIAutomationCore.dll not loadable"
            return None
        try:
            self._coinit_hr = _ole32.CoInitialize(None) & 0xFFFFFFFF
            ptr = c_void_p()
            hr = _ole32.CoCreateInstance(
                byref(_parse_guid(CLSID_CUIAutomation)),
                None,
                CLSCTX_INPROC_SERVER,
                byref(_parse_guid(IID_IUIAutomation)),
                byref(ptr),
            )
            if hr != S_OK or not ptr.value:
                self._error = f"CoCreateInstance hr={hr & 0xFFFFFFFF:#x}"
                return None
            self._uia = ptr
            return ctypes.cast(ptr, POINTER(_IUIAutomation))
        except Exception as exc:  # pragma: no cover - 环境相关
            self._error = f"CoCreateInstance exception: {exc}"
            self._uia = None
            return None

    def close(self) -> None:
        if self._uia is not None:
            _release(self._uia)
            self._uia = None
        if self._true_condition is not None:
            _release(self._true_condition)
            self._true_condition = None
        if self._coinit_hr is not None and not self._closed:
            try:
                _ole32.CoUninitialize()
            except Exception:
                pass
        self._closed = True

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass

    def _condition(self) -> c_void_p | None:
        uia = self._ensure()
        if uia is None:
            return None
        if self._true_condition is not None:
            return self._true_condition
        cond = c_void_p()
        try:
            hr = uia.contents.lpVtbl.contents.CreateTrueCondition(uia, byref(cond))
            if hr == S_OK and cond.value:
                self._true_condition = cond
                return cond
        except Exception:
            pass
        return None

    # ---- ElementSource 协议 ----

    def element_from_handle(self, hwnd: int) -> c_void_p | None:
        uia = self._ensure()
        if uia is None or not hwnd:
            return None
        out = c_void_p()
        try:
            hr = uia.contents.lpVtbl.contents.ElementFromHandle(uia, int(hwnd), byref(out))
            if hr == S_OK and out.value:
                return out
        except Exception:
            pass
        return None

    def get_property(self, element, prop_id: int):
        if element is None:
            return None
        elem = ctypes.cast(element, POINTER(_IUIAutomationElement))
        buf = (ctypes.c_ubyte * 16)()
        try:
            hr = elem.contents.lpVtbl.contents.GetCurrentPropertyValue(elem, int(prop_id), byref(buf))
        except Exception:
            return None
        if hr != S_OK:
            return None
        vt = buf[0] | (buf[1] << 8)
        if vt == VT_I4:
            return struct.unpack_from("<i", bytes(buf), 8)[0]
        if vt == VT_BSTR:
            ptr = int.from_bytes(bytes(buf)[8:16], "little")
            # UIA 对不支持的属性返回保留哨兵 BSTR，禁止解引用/释放
            if not ptr or not (0x10000 <= ptr <= 0x00007FFFFFFFFFFF):
                return None
            try:
                text = ctypes.wstring_at(ptr)
            except Exception:
                return None
            try:
                _oleaut32.SysFreeString(ptr)
            except Exception:
                pass
            return text
        return None

    def children(self, element) -> list:
        if element is None:
            return []
        elem = ctypes.cast(element, POINTER(_IUIAutomationElement))
        cond = self._condition()
        if cond is None:
            return []
        arr = c_void_p()
        try:
            hr = elem.contents.lpVtbl.contents.FindAll(elem, TreeScope_Children, cond, byref(arr))
        except Exception:
            return []  # 个别元素 FindAll E_FAIL：按叶子处理
        if hr != S_OK or not arr.value:
            return []
        array = ctypes.cast(arr, POINTER(_IUIAutomationElementArray))
        length = c_int()
        try:
            array.contents.lpVtbl.contents.get_Length(array, byref(length))
            count = max(0, length.value)
            out: list = []
            for i in range(count):
                child = c_void_p()
                hr2 = array.contents.lpVtbl.contents.get_Element(array, i, byref(child))
                if hr2 == S_OK and child.value:
                    out.append(child)
            return out
        except Exception:
            return []
        finally:
            _release(arr)

    def get_pattern(self, element, pattern_id: int):
        if element is None:
            return None
        elem = ctypes.cast(element, POINTER(_IUIAutomationElement))
        pat = c_void_p()
        try:
            hr = elem.contents.lpVtbl.contents.GetCurrentPattern(elem, int(pattern_id), byref(pat))
        except Exception:
            return None  # E_NOINTERFACE 等：控件不支持该 pattern
        if hr == S_OK and pat.value:
            return pat
        return None

    def invoke(self, pattern) -> None:
        if pattern is None:
            return
        p = ctypes.cast(pattern, POINTER(_IUIAutomationInvokePattern))
        try:
            p.contents.lpVtbl.contents.Invoke(p)
        except Exception:
            pass

    def set_value(self, pattern, text: str) -> None:
        if pattern is None:
            return
        p = ctypes.cast(pattern, POINTER(_IUIAutomationValuePattern))
        bstr = None
        try:
            bstr = _oleaut32.SysAllocString(str(text))
            if not bstr:
                return
            p.contents.lpVtbl.contents.SetValue(p, bstr)
        except Exception:
            pass
        finally:
            if bstr:
                try:
                    _oleaut32.SysFreeString(bstr)
                except Exception:
                    pass

    def toggle(self, pattern) -> None:
        if pattern is None:
            return
        p = ctypes.cast(pattern, POINTER(_IUIAutomationTogglePattern))
        try:
            p.contents.lpVtbl.contents.Toggle(p)
        except Exception:
            pass

    def value(self, pattern) -> str:
        if pattern is None:
            return ""
        p = ctypes.cast(pattern, POINTER(_IUIAutomationValuePattern))
        out = c_void_p()
        try:
            hr = p.contents.lpVtbl.contents.get_CurrentValue(p, byref(out))
            if hr != S_OK or not out.value:
                return ""
            try:
                return ctypes.wstring_at(out)
            finally:
                try:
                    _oleaut32.SysFreeString(out)
                except Exception:
                    pass
        except Exception:
            return ""

    def toggle_state(self, pattern) -> int:
        if pattern is None:
            return -1
        p = ctypes.cast(pattern, POINTER(_IUIAutomationTogglePattern))
        out = c_int()
        try:
            hr = p.contents.lpVtbl.contents.get_CurrentToggleState(p, byref(out))
            return out.value if hr == S_OK else -1
        except Exception:
            return -1
