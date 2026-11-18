"""COM interfaces of WebView2, written by tools/make_webview2_com.py from WebView2.h
(Microsoft.Web.WebView2 1.0.4314.35). Do not edit; run the tool again instead."""

# ruff: noqa
import ctypes
from ctypes import HRESULT, wintypes

from comtypes import COMMETHOD, GUID, IUnknown
from comtypes.automation import VARIANT


class COREWEBVIEW2_COLOR(ctypes.Structure):
    _fields_ = [("A", ctypes.c_ubyte), ("R", ctypes.c_ubyte), ("G", ctypes.c_ubyte), ("B", ctypes.c_ubyte)]


class EventRegistrationToken(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int64)]


class ICoreWebView2Environment(IUnknown):
    _iid_ = GUID("{B96D755E-0319-4E92-A296-23436F46A1FC}")


class ICoreWebView2Environment2(ICoreWebView2Environment):
    _iid_ = GUID("{41F3632B-5EF4-404F-AD82-2D606C5A9A21}")


class ICoreWebView2Environment3(ICoreWebView2Environment2):
    _iid_ = GUID("{80A22AE3-BE7C-4CE2-AFE1-5A50056CDEEB}")


class ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler(IUnknown):
    _iid_ = GUID("{4E8A3389-C9D8-4BD2-B6B5-124FEE6CC14D}")


class ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler(IUnknown):
    _iid_ = GUID("{02FAB84B-1428-4FB7-AD45-1B2E64736184}")


class ICoreWebView2CompositionController(IUnknown):
    _iid_ = GUID("{3DF9B733-B9AE-4A15-86B4-EB9EE9826469}")


class ICoreWebView2Controller(IUnknown):
    _iid_ = GUID("{4D00C0D1-9434-4EB6-8078-8697A560334F}")


class ICoreWebView2Controller2(ICoreWebView2Controller):
    _iid_ = GUID("{C979903E-D4CA-4228-92EB-47EE3FA96EAB}")


class ICoreWebView2Controller3(ICoreWebView2Controller2):
    _iid_ = GUID("{F9614724-5D2B-41DC-AEF7-73D62B51543B}")


class ICoreWebView2(IUnknown):
    _iid_ = GUID("{76ECEACB-0462-4D94-AC83-423A6793775E}")


class ICoreWebView2Settings(IUnknown):
    _iid_ = GUID("{E562E4F0-D7FA-43AC-8D71-C05150499F00}")


class ICoreWebView2ExecuteScriptCompletedHandler(IUnknown):
    _iid_ = GUID("{49511172-CC67-4BCA-9923-137112F4C4CC}")


class ICoreWebView2NavigationCompletedEventHandler(IUnknown):
    _iid_ = GUID("{D33A35BF-1C49-4F98-93AB-006E0533FE1C}")


class ICoreWebView2NavigationCompletedEventArgs(IUnknown):
    _iid_ = GUID("{30D68B7D-20D9-4752-A9CA-EC8448FBB5C1}")

ICoreWebView2Environment._methods_ = [
    COMMETHOD([], HRESULT, 'CreateCoreWebView2Controller', (['in'], wintypes.HWND, 'parentWindow'), (['in'], ctypes.c_void_p, 'handler')),
    COMMETHOD([], HRESULT, 'CreateWebResourceResponse', (['in'], ctypes.c_void_p, 'content'), (['in'], ctypes.c_int, 'statusCode'), (['in'], wintypes.LPCWSTR, 'reasonPhrase'), (['in'], wintypes.LPCWSTR, 'headers'), (['out', 'retval'], ctypes.POINTER(ctypes.c_void_p), 'response')),
    COMMETHOD([], HRESULT, 'get_BrowserVersionString', (['out', 'retval'], ctypes.POINTER(ctypes.c_void_p), 'versionInfo')),
    COMMETHOD([], HRESULT, 'add_NewBrowserVersionAvailable', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_NewBrowserVersionAvailable', (['in'], EventRegistrationToken, 'token')),
]
ICoreWebView2Environment2._methods_ = [
    COMMETHOD([], HRESULT, 'CreateWebResourceRequest', (['in'], wintypes.LPCWSTR, 'uri'), (['in'], wintypes.LPCWSTR, 'Method'), (['in'], ctypes.c_void_p, 'postData'), (['in'], wintypes.LPCWSTR, 'Headers'), (['out', 'retval'], ctypes.POINTER(ctypes.c_void_p), 'value')),
]
ICoreWebView2Environment3._methods_ = [
    COMMETHOD([], HRESULT, 'CreateCoreWebView2CompositionController', (['in'], wintypes.HWND, 'ParentWindow'), (['in'], ctypes.POINTER(ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler), 'handler')),
    COMMETHOD([], HRESULT, 'CreateCoreWebView2PointerInfo', (['out', 'retval'], ctypes.POINTER(ctypes.c_void_p), 'value')),
]
ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler._methods_ = [
    COMMETHOD([], HRESULT, 'Invoke', (['in'], HRESULT, 'errorCode'), (['in'], ctypes.POINTER(ICoreWebView2Environment), 'result')),
]
ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler._methods_ = [
    COMMETHOD([], HRESULT, 'Invoke', (['in'], HRESULT, 'errorCode'), (['in'], ctypes.POINTER(ICoreWebView2CompositionController), 'result')),
]
ICoreWebView2CompositionController._methods_ = [
    COMMETHOD([], HRESULT, 'get_RootVisualTarget', (['out', 'retval'], ctypes.POINTER(ctypes.POINTER(IUnknown)), 'target')),
    COMMETHOD([], HRESULT, 'put_RootVisualTarget', (['in'], ctypes.POINTER(IUnknown), 'target')),
    COMMETHOD([], HRESULT, 'SendMouseInput', (['in'], ctypes.c_int, 'eventKind'), (['in'], ctypes.c_int, 'virtualKeys'), (['in'], ctypes.c_uint32, 'mouseData'), (['in'], wintypes.POINT, 'point')),
    COMMETHOD([], HRESULT, 'SendPointerInput', (['in'], ctypes.c_int, 'eventKind'), (['in'], ctypes.c_void_p, 'pointerInfo')),
    COMMETHOD([], HRESULT, 'get_Cursor', (['out', 'retval'], ctypes.POINTER(wintypes.HANDLE), 'cursor')),
    COMMETHOD([], HRESULT, 'get_SystemCursorId', (['out', 'retval'], ctypes.POINTER(ctypes.c_uint32), 'systemCursorId')),
    COMMETHOD([], HRESULT, 'add_CursorChanged', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_CursorChanged', (['in'], EventRegistrationToken, 'token')),
]
ICoreWebView2Controller._methods_ = [
    COMMETHOD([], HRESULT, 'get_IsVisible', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'isVisible')),
    COMMETHOD([], HRESULT, 'put_IsVisible', (['in'], wintypes.BOOL, 'isVisible')),
    COMMETHOD([], HRESULT, 'get_Bounds', (['out', 'retval'], ctypes.POINTER(wintypes.RECT), 'bounds')),
    COMMETHOD([], HRESULT, 'put_Bounds', (['in'], wintypes.RECT, 'bounds')),
    COMMETHOD([], HRESULT, 'get_ZoomFactor', (['out', 'retval'], ctypes.POINTER(ctypes.c_double), 'zoomFactor')),
    COMMETHOD([], HRESULT, 'put_ZoomFactor', (['in'], ctypes.c_double, 'zoomFactor')),
    COMMETHOD([], HRESULT, 'add_ZoomFactorChanged', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_ZoomFactorChanged', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'SetBoundsAndZoomFactor', (['in'], wintypes.RECT, 'bounds'), (['in'], ctypes.c_double, 'zoomFactor')),
    COMMETHOD([], HRESULT, 'MoveFocus', (['in'], ctypes.c_int, 'reason')),
    COMMETHOD([], HRESULT, 'add_MoveFocusRequested', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_MoveFocusRequested', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_GotFocus', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_GotFocus', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_LostFocus', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_LostFocus', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_AcceleratorKeyPressed', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_AcceleratorKeyPressed', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'get_ParentWindow', (['out', 'retval'], ctypes.POINTER(wintypes.HWND), 'parentWindow')),
    COMMETHOD([], HRESULT, 'put_ParentWindow', (['in'], wintypes.HWND, 'parentWindow')),
    COMMETHOD([], HRESULT, 'NotifyParentWindowPositionChanged'),
    COMMETHOD([], HRESULT, 'Close'),
    COMMETHOD([], HRESULT, 'get_CoreWebView2', (['out', 'retval'], ctypes.POINTER(ctypes.POINTER(ICoreWebView2)), 'coreWebView2')),
]
ICoreWebView2Controller2._methods_ = [
    COMMETHOD([], HRESULT, 'get_DefaultBackgroundColor', (['out', 'retval'], ctypes.POINTER(COREWEBVIEW2_COLOR), 'value')),
    COMMETHOD([], HRESULT, 'put_DefaultBackgroundColor', (['in'], COREWEBVIEW2_COLOR, 'value')),
]
ICoreWebView2Controller3._methods_ = [
    COMMETHOD([], HRESULT, 'get_RasterizationScale', (['out', 'retval'], ctypes.POINTER(ctypes.c_double), 'scale')),
    COMMETHOD([], HRESULT, 'put_RasterizationScale', (['in'], ctypes.c_double, 'scale')),
    COMMETHOD([], HRESULT, 'get_ShouldDetectMonitorScaleChanges', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'value')),
    COMMETHOD([], HRESULT, 'put_ShouldDetectMonitorScaleChanges', (['in'], wintypes.BOOL, 'value')),
    COMMETHOD([], HRESULT, 'add_RasterizationScaleChanged', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_RasterizationScaleChanged', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'get_BoundsMode', (['out', 'retval'], ctypes.POINTER(ctypes.c_int), 'boundsMode')),
    COMMETHOD([], HRESULT, 'put_BoundsMode', (['in'], ctypes.c_int, 'boundsMode')),
]
ICoreWebView2._methods_ = [
    COMMETHOD([], HRESULT, 'get_Settings', (['out', 'retval'], ctypes.POINTER(ctypes.POINTER(ICoreWebView2Settings)), 'settings')),
    COMMETHOD([], HRESULT, 'get_Source', (['out', 'retval'], ctypes.POINTER(ctypes.c_void_p), 'uri')),
    COMMETHOD([], HRESULT, 'Navigate', (['in'], wintypes.LPCWSTR, 'uri')),
    COMMETHOD([], HRESULT, 'NavigateToString', (['in'], wintypes.LPCWSTR, 'htmlContent')),
    COMMETHOD([], HRESULT, 'add_NavigationStarting', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_NavigationStarting', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_ContentLoading', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_ContentLoading', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_SourceChanged', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_SourceChanged', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_HistoryChanged', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_HistoryChanged', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_NavigationCompleted', (['in'], ctypes.POINTER(ICoreWebView2NavigationCompletedEventHandler), 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_NavigationCompleted', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_FrameNavigationStarting', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_FrameNavigationStarting', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_FrameNavigationCompleted', (['in'], ctypes.POINTER(ICoreWebView2NavigationCompletedEventHandler), 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_FrameNavigationCompleted', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_ScriptDialogOpening', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_ScriptDialogOpening', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_PermissionRequested', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_PermissionRequested', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_ProcessFailed', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_ProcessFailed', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'AddScriptToExecuteOnDocumentCreated', (['in'], wintypes.LPCWSTR, 'javaScript'), (['in'], ctypes.c_void_p, 'handler')),
    COMMETHOD([], HRESULT, 'RemoveScriptToExecuteOnDocumentCreated', (['in'], wintypes.LPCWSTR, 'id')),
    COMMETHOD([], HRESULT, 'ExecuteScript', (['in'], wintypes.LPCWSTR, 'javaScript'), (['in'], ctypes.POINTER(ICoreWebView2ExecuteScriptCompletedHandler), 'handler')),
    COMMETHOD([], HRESULT, 'CapturePreview', (['in'], ctypes.c_int, 'imageFormat'), (['in'], ctypes.c_void_p, 'imageStream'), (['in'], ctypes.c_void_p, 'handler')),
    COMMETHOD([], HRESULT, 'Reload'),
    COMMETHOD([], HRESULT, 'PostWebMessageAsJson', (['in'], wintypes.LPCWSTR, 'webMessageAsJson')),
    COMMETHOD([], HRESULT, 'PostWebMessageAsString', (['in'], wintypes.LPCWSTR, 'webMessageAsString')),
    COMMETHOD([], HRESULT, 'add_WebMessageReceived', (['in'], ctypes.c_void_p, 'handler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_WebMessageReceived', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'CallDevToolsProtocolMethod', (['in'], wintypes.LPCWSTR, 'methodName'), (['in'], wintypes.LPCWSTR, 'parametersAsJson'), (['in'], ctypes.c_void_p, 'handler')),
    COMMETHOD([], HRESULT, 'get_BrowserProcessId', (['out', 'retval'], ctypes.POINTER(ctypes.c_uint32), 'value')),
    COMMETHOD([], HRESULT, 'get_CanGoBack', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'canGoBack')),
    COMMETHOD([], HRESULT, 'get_CanGoForward', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'canGoForward')),
    COMMETHOD([], HRESULT, 'GoBack'),
    COMMETHOD([], HRESULT, 'GoForward'),
    COMMETHOD([], HRESULT, 'GetDevToolsProtocolEventReceiver', (['in'], wintypes.LPCWSTR, 'eventName'), (['out', 'retval'], ctypes.POINTER(ctypes.c_void_p), 'receiver')),
    COMMETHOD([], HRESULT, 'Stop'),
    COMMETHOD([], HRESULT, 'add_NewWindowRequested', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_NewWindowRequested', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'add_DocumentTitleChanged', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_DocumentTitleChanged', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'get_DocumentTitle', (['out', 'retval'], ctypes.POINTER(ctypes.c_void_p), 'title')),
    COMMETHOD([], HRESULT, 'AddHostObjectToScript', (['in'], wintypes.LPCWSTR, 'name'), (['in'], ctypes.POINTER(VARIANT), 'object')),
    COMMETHOD([], HRESULT, 'RemoveHostObjectFromScript', (['in'], wintypes.LPCWSTR, 'name')),
    COMMETHOD([], HRESULT, 'OpenDevToolsWindow'),
    COMMETHOD([], HRESULT, 'add_ContainsFullScreenElementChanged', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_ContainsFullScreenElementChanged', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'get_ContainsFullScreenElement', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'containsFullScreenElement')),
    COMMETHOD([], HRESULT, 'add_WebResourceRequested', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_WebResourceRequested', (['in'], EventRegistrationToken, 'token')),
    COMMETHOD([], HRESULT, 'AddWebResourceRequestedFilter', (['in'], wintypes.LPCWSTR, 'uri'), (['in'], ctypes.c_int, 'resourceContext')),
    COMMETHOD([], HRESULT, 'RemoveWebResourceRequestedFilter', (['in'], wintypes.LPCWSTR, 'uri'), (['in'], ctypes.c_int, 'resourceContext')),
    COMMETHOD([], HRESULT, 'add_WindowCloseRequested', (['in'], ctypes.c_void_p, 'eventHandler'), (['out'], ctypes.POINTER(EventRegistrationToken), 'token')),
    COMMETHOD([], HRESULT, 'remove_WindowCloseRequested', (['in'], EventRegistrationToken, 'token')),
]
ICoreWebView2Settings._methods_ = [
    COMMETHOD([], HRESULT, 'get_IsScriptEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'isScriptEnabled')),
    COMMETHOD([], HRESULT, 'put_IsScriptEnabled', (['in'], wintypes.BOOL, 'isScriptEnabled')),
    COMMETHOD([], HRESULT, 'get_IsWebMessageEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'isWebMessageEnabled')),
    COMMETHOD([], HRESULT, 'put_IsWebMessageEnabled', (['in'], wintypes.BOOL, 'isWebMessageEnabled')),
    COMMETHOD([], HRESULT, 'get_AreDefaultScriptDialogsEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'areDefaultScriptDialogsEnabled')),
    COMMETHOD([], HRESULT, 'put_AreDefaultScriptDialogsEnabled', (['in'], wintypes.BOOL, 'areDefaultScriptDialogsEnabled')),
    COMMETHOD([], HRESULT, 'get_IsStatusBarEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'isStatusBarEnabled')),
    COMMETHOD([], HRESULT, 'put_IsStatusBarEnabled', (['in'], wintypes.BOOL, 'isStatusBarEnabled')),
    COMMETHOD([], HRESULT, 'get_AreDevToolsEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'areDevToolsEnabled')),
    COMMETHOD([], HRESULT, 'put_AreDevToolsEnabled', (['in'], wintypes.BOOL, 'areDevToolsEnabled')),
    COMMETHOD([], HRESULT, 'get_AreDefaultContextMenusEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'enabled')),
    COMMETHOD([], HRESULT, 'put_AreDefaultContextMenusEnabled', (['in'], wintypes.BOOL, 'enabled')),
    COMMETHOD([], HRESULT, 'get_AreHostObjectsAllowed', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'allowed')),
    COMMETHOD([], HRESULT, 'put_AreHostObjectsAllowed', (['in'], wintypes.BOOL, 'allowed')),
    COMMETHOD([], HRESULT, 'get_IsZoomControlEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'enabled')),
    COMMETHOD([], HRESULT, 'put_IsZoomControlEnabled', (['in'], wintypes.BOOL, 'enabled')),
    COMMETHOD([], HRESULT, 'get_IsBuiltInErrorPageEnabled', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'enabled')),
    COMMETHOD([], HRESULT, 'put_IsBuiltInErrorPageEnabled', (['in'], wintypes.BOOL, 'enabled')),
]
ICoreWebView2ExecuteScriptCompletedHandler._methods_ = [
    COMMETHOD([], HRESULT, 'Invoke', (['in'], HRESULT, 'errorCode'), (['in'], wintypes.LPCWSTR, 'result')),
]
ICoreWebView2NavigationCompletedEventHandler._methods_ = [
    COMMETHOD([], HRESULT, 'Invoke', (['in'], ctypes.POINTER(ICoreWebView2), 'sender'), (['in'], ctypes.POINTER(ICoreWebView2NavigationCompletedEventArgs), 'args')),
]
ICoreWebView2NavigationCompletedEventArgs._methods_ = [
    COMMETHOD([], HRESULT, 'get_IsSuccess', (['out', 'retval'], ctypes.POINTER(wintypes.BOOL), 'isSuccess')),
    COMMETHOD([], HRESULT, 'get_WebErrorStatus', (['out', 'retval'], ctypes.POINTER(ctypes.c_int), 'webErrorStatus')),
    COMMETHOD([], HRESULT, 'get_NavigationId', (['out', 'retval'], ctypes.POINTER(ctypes.c_uint64), 'navigationId')),
]
