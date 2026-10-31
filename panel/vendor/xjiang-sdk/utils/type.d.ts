export type TStateKey = 'data' | 'info' | 'status' | 'init';

export type PageFuncType = {
  key?: string;
  onLoad?: (options: any) => void;
  onReady?: () => void;
  onShow?: () => void;
  onHide?: () => void;
  onUnload?: () => void;
  onDeviceInfoChange?: (data: any) => void;
  onDeviceDataReport?: (data: any) => void;
  onDeviceDataChange?: (data: any) => void;

  onGetDarkMode?: (isDarkMode: boolean) => void;
  onBleStateChange?: (bleState: number) => void;
  onBleConnectStateChange?: (connectState: number) => void;
  onOTAInfoChange?: (otaInfo: any) => void;

  onPageConnectChange?: (error: boolean) => void; // websocket连接状态 主要用于连接失败页面提示
  onPageInit?: (data: any) => void; // 项目初始化

  onDataStateChange?: (data: any) => void;
}

export type NavButtons = {
  type?: number;  // 1: 通用设置
  title?: string;  //	标题
  image?: string;  //	图片资源地址
  badge?: boolean;  // 小红点
  action?: void;
}

export type OtaInfoType = {
  version: string;
  availableVersion: string;
  updateDetail: string;
  forceUpgradeDescription: string;
  remindType: number; // 0: 不需要升级；  1：需要升级；  2：需要强制升级
  isRuning: number; // 正在升级
  progress: number; // 升级进度
}

export type OtaParamsType = {
  progress?: (value: any) => void;
  result?: (value: { code: number, ok: boolean }) => void;
}

export type ConfigType = {
  type: "wifi" | "ble" | "mesh";
  shouldWaitTo_getSnapshot?: boolean;
  basicConfig?: {
    defaultData?: boolean;
  };
  info?: object;
  data?: object;
}

export type DeviceDataType = {
  data: object;
  info: object;
  getDeviceInfo?: () => void;
  getSnapshot?: () => void;
  bleConnect?: () => void;
  bleDisConnect?: () => void;
  get?: (keys: string[]) => void;
  set?: (data: object, okStates?: object) => Promise;
  reconnect?: () => void;
}

export type DataResultType = { 
  msgId: number;
  ok: boolean;
  errorCode: number;
  values?: string[] | number[];
}

export type BleResultType = {
  ok: boolean;
  errorCode: number;  // 0: 没有错误；1: 不是蓝牙设备；2:蓝牙不可用；3:没有蓝牙权限；4:手机没有打开蓝牙；5.设备已连接（不需要再次连接了）；6: 没有搜索到设备；7:设备认证失败；8:连接超时；9:连接被取消；10:连接失败
}