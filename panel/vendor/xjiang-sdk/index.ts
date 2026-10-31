import WeappApi from "./api/weapp";
import type {
  ConfigType,
  PageFuncType,
  DeviceDataType
} from "./utils/type.d.ts";
import AppApi from "./api/app";

const isMiniProgramEnv =
  window.__wxjs_environment === "miniprogram" ||
  (typeof window.__wxjs_environment === "undefined" &&
    /MicroMessenger/i.test(navigator.userAgent));

export default class XJIotSDK {
  /***
   * 连接方式   0：app   1：weapp
   */
  connectType: number = isMiniProgramEnv ? 1 : 0;
  // connectType: number = 1;
  _weappApi: any = null;
  _appApi: any = AppApi;

  /***
   * 页面websocket连接状态
   */
  pageConnectState: boolean = true;
  /***
   * 蓝牙状态    0：未知；  1：不可用；   2：未授权；   3：未打开；   4：可用
   */
  bleState: number = 0;

  /***
   * 蓝牙设备连接状态    0：未连接；  1：正在搜索；  2：正在连接；  3：已连接；  4：就绪
   */
  bleConnectState: number = 0;
  device: DeviceDataType = {
    data: {},
    info: {}
  };
  config: any = {};
  file = {};
  xj: any = {};
  initData: any = {};

  constructor(config: ConfigType) {
    console.log(
      "[env-detect] XJIotSDK constructor | connectType =",
      this.connectType,
      "| 0=app/RN  1=weapp"
    );
    if (this.connectType) {
      this._weappApi = new WeappApi(config);
      this.device = { ...this._weappApi?.states, ...this._weappApi?.device };
    } else {
      this._appApi = new AppApi(config);
      this.xj = this._appApi?.xj;

      this.device = { ...this.device, ...this.xj?.device };
      this.config = this.xj?.config;
      this.file = this.xj?.file;
    }
    const api = this.connectType ? this._weappApi : this._appApi;
    this.bleState = api?.states?.status?.bleState;
    this.bleConnectState = api?.states?.status?.bleConnectState;
    this.pageConnectState = api?.states?.status?.pageConnectState;
  }

  initProject(callbacks: PageFuncType) {
    if (this.connectType) {
      this._weappApi.initDevice(callbacks);
    } else {
      this._appApi.initDevice(callbacks);
    }
  }

  /***
   * 初始化页面，每个页面单独处理
   */
  pageInit(params: PageFuncType) {
    if (this.connectType) {
      this._weappApi.pageInit(params);
    } else {
      this._appApi.pageInit(params);
    }
  }

  importProtocol(params) {
    if (this.connectType) {
      // this._weappApi.importProtocol(params);
    } else {
      this._appApi.importProtocol(params);
    }
  }

  showAlert(params) {
    if (this.connectType) {
      // this._weappApi.showAlert(params);
    } else {
      this._appApi.showAlert(params);
    }
  }
  showPicker(params) {
    if (this.connectType) {
      // this._weappApi.showPicker(params);
    } else {
      this._appApi.showPicker(params);
    }
  }
  showToast(params) {
    if (this.connectType) {
      // this._weappApi.showToast(params);
    } else {
      this._appApi.showToast(params);
    }
  }
  hideToast() {
    if (this.connectType) {
      // this._weappApi.hideToast();
    } else {
      this._appApi.hideToast();
    }
  }
  showNavigationBar() {
    if (this.connectType) {
      // this._weappApi.showNavigationBar(params);
    } else {
      this._appApi.showNavigationBar();
    }
  }
  hideNavigationBar() {
    if (this.connectType) {
      // this._weappApi.hideNavigationBar();
    } else {
      this._appApi.hideNavigationBar();
    }
  }

  openSettingsPage(params) {
    if (this.connectType) {
      this._weappApi.openSettingsPage(params);
    } else {
      this._appApi.openSettingsPage(params);
    }
  }

  /***
   * 退出H5页面
   */
  exit() {
    if (this.connectType) {
      this._weappApi.exitPage();
    } else {
      this._appApi.exit();
    }
  }

  /***
   * 刷新页面
   */
  reload() {
    if (this.connectType) {
      this._weappApi.reload();
    } else {
      this._appApi.reload();
    }
  }

  /***
   * 本地更改数据，不下发
   */
  setAttrs(data) {
    if (this.connectType) {
      this._weappApi.setAttrs(data);
    } else {
      this._appApi.setAttrs(data);
    }
  }
}
