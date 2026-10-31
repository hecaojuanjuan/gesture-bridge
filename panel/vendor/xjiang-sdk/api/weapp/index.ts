import WS from "./webSocket";
import Data from "../data";
import type {
  ConfigType,
  TStateKey,
  PageFuncType,
  NavButtons,
  OtaInfoType,
  OtaParamsType
} from "../../utils/type.d.ts";
import { getUrlQueryString } from "../../utils";
import { loading, popup } from "../../../xjiang-ui";

const isDebug = import.meta.env?.MODE === "debug"; // 是否开启调试模式

function handleConfig2Protocol(config) {
  let _c = {},
    _d = {},
    _k = {};
  if (config) {
    for (const k in config) {
      if (k && config[k]) {
        _c = { ..._c, [`${k}`]: { key: config[k]?.key } };
        _d = { ..._d, [`${k}`]: config[k]?.value };
        _k = { ..._k, [`${config[k]?.key}`]: k };
      }
    }
  }
  return { protocol: _c, data: _d, protocolKeys: _k };
}
function handleProtocol2Key(keys: string[], protocol) {
  if (!keys || !keys.length) return null;

  let propKeys = [];
  if (protocol) {
    for (const k of keys) {
      if (k in protocol) {
        const _propKey = protocol[k];
        if (_propKey?.key) {
          propKeys = [...propKeys, _propKey?.key];
        } else {
          propKeys = [...propKeys, k];
        }
      } else {
        propKeys = [...propKeys, k];
      }
    }
  }
  return propKeys;
}
function handleProtocol2Value(values, protocolKeys, IgnoreAttrs) {
  let keyVals = {};
  if (values) {
    for (const v in values) {
      if (protocolKeys) {
        if (v in protocolKeys && !IgnoreAttrs.includes(protocolKeys[v])) {
          keyVals = { ...keyVals, [`${protocolKeys[v]}`]: values[v] };
        }
      }
    }
  }
  return keyVals;
}

export default class WeappApi extends Data {
  connectCount: number = 0;
  ws: any;
  callbackTimers: any = {};
  callbackCache: any = {};
  heatBeat: number = 0;
  SetSyncTimer: NodeJS.Timeout;
  protocolConfig = { data: {}, protocol: {}, protocolKeys: {} }; // 设备协议转换成内部格式
  protocol: any;
  popupLoading: any;
  IgnoreAttrs: string[] = [];
  private isPageVisible = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private lifecycleBound = false;
  private shouldShowConnectLoading = true;

  // WebSocket 未就绪时的发送队列
  private pendingSend: Array<{ method: string; params?: any; data?: any }> = [];

  //#region websocket数据交互
  /***
   * websocket下发
   */
  webSocketSend(method: string, data?: any) {
    const msg = { method, params: data || null, data: data || null };
    if (this.ws?.ws?.readyState === WebSocket.OPEN) {
      return this.ws.send(msg);
    }
    // WebSocket 未就绪，先缓存
    this.pendingSend.push(msg);
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private scheduleReconnect(delay = 50) {
    if (!this.isPageVisible) {
      return;
    }
    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.initWS();
    }, delay);
  }

  private handlePageHide() {
    this.isPageVisible = false;
    this.shouldShowConnectLoading = false;
    this.clearReconnectTimer();
    this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
    this.bleConnectTimer && clearTimeout(this.bleConnectTimer);
    this.popupLoading && this.popupLoading.close();
  }

  private handlePageShow() {
    const wasHidden = !this.isPageVisible;
    this.isPageVisible = true;
    if (!wasHidden) {
      return;
    }
    this.shouldShowConnectLoading = false;
    const readyState = this.ws?.ws?.readyState;
    if (readyState === WebSocket.OPEN || readyState === WebSocket.CONNECTING) {
      this.setState("status", { pageConnectState: true });
      return;
    }
    this.connectCount = 0;
    this.heatBeat = 0;
    this.scheduleReconnect(0);
  }

  private bindLifecycleEvents() {
    if (this.lifecycleBound || typeof document === "undefined") {
      return;
    }
    document.addEventListener("visibilitychange", this.onVisibilityChange);
    window.addEventListener("pagehide", this.onPageHide);
    window.addEventListener("pageshow", this.onPageShow);
    this.lifecycleBound = true;
  }

  private unbindLifecycleEvents() {
    if (!this.lifecycleBound || typeof document === "undefined") {
      return;
    }
    document.removeEventListener("visibilitychange", this.onVisibilityChange);
    window.removeEventListener("pagehide", this.onPageHide);
    window.removeEventListener("pageshow", this.onPageShow);
    this.lifecycleBound = false;
  }

  private onVisibilityChange = () => {
    if (document.hidden) {
      this.handlePageHide();
      return;
    }
    this.handlePageShow();
  };

  private onPageHide = () => {
    this.handlePageHide();
  };

  private onPageShow = () => {
    this.handlePageShow();
  };

  /** 处理推送信息 */
  onMessage(messageData: { method?: string; params?: any; data?: any }) {
    const { method, params, data } = messageData;
    switch (method) {
      // stringInit
      case "stringsInit": {
        const languageCode = params?.code || "zh-CN";
        this.setState("init", { languageCode });
        setTimeout(() => {
          this.popupLoading && this.popupLoading.close();
        }, 800);
        break;
      }
      case "onShow": {
        setTimeout(() => {
          this.popupLoading && this.popupLoading.close();
        }, 800);
        break;
      }
      case "onLoad": {
        this.device.get([]);
        break;
      }
      // 监听设备状态
      case "onDeviceOnline":
        const isOnline = !!(params ?? false);
        this.setState("init", { isOnline });
        break;
      // 心跳请求
      case "keepAlive":
        this.webSocketSend("keepAlive_reply", data);
        if (!this.heatBeat) {
          this.setState("init", { initComplete: true });
          this.initProject();
        }
        this.heatBeat++;
        break;
      // 获取设备信息上报  ||   上报设备信息  ||  设备信息变更
      case "getDeviceInfo_reply":
      case "reportDeviceInfo":
      case "onDeviceInfoChange":
        this.setState("info", params);
        break;
      // 查询设备快照上报  ||   查询属性上报  ||  上报设备数据
      case "getDeviceSnapshot_reply":
      case "getAttrs_reply":
      case "onDeviceDataChange":
        try {
          let _params = params;
          if (typeof params === "string") {
            _params = JSON.parse(params);
          }
          const _d = handleProtocol2Value(
            _params,
            this.protocolConfig.protocolKeys,
            this.IgnoreAttrs
          );

          // let _newData = {};
          // if (this.IgnoreAttrs) {
          //   for (const k in data) {
          //     if (!this.IgnoreAttrs.includes(k)) {
          //       _newData = { ..._newData, [`${ k }`]: data[k] };
          //     }
          //   }
          // } else _newData = data;
          // this.xj.device.data = this.handleProtocol2Value(_newData)
          // this.setState("data", this.xj.device.data);

          this.setState("data", _d);
          this.setState("status", { getDeviceSnapshot: true });
        } catch (e) {}
        break;
      // 上报设备状态
      case "reportDeviceStatus":
        break;
      // 发送属性回复
      case "sendAttrs_reply":
        if (data.code === 0) {
          // 下发成功
        } else {
          // 下发失败
        }
        break;
      // 上报蓝牙连接状态
      case "onBleConnectChange":
        setTimeout(() => {
          this.popupLoading && this.popupLoading.close();
        }, 300);
        this.setState("status", { bleConnectState: params.connectStatus });

        if (!params.connectStatus || params.connectStatus === 2) {
          this.bleConnectTimer && clearTimeout(this.bleConnectTimer);
        }
        break;
      // 连接设备成功reply--暂不用，主要用onBleConnectChange
      case "connect_reply":
        break;
      // 小程序宿主回传请求头，转发给 nativeApiRequestHeaders 的 waiter 回调
      case "getReqHeaders":
        (window as any).xj?.getReqHeaders?.(params);
        break;
      case "player": {
        const playerPayload = params?.method === "playerReply" ? params : null;
        const playerParams =
          playerPayload?.params ?? params?.params ?? data?.params ?? {};
        this.setState("init", {
          mediaPlayer: playerParams
        });
        break;
      }
      default:
        break;
    }
  }

  /***
   * 初始化Websocket
   */
  initWS() {
    if (!this.isPageVisible) {
      return;
    }
    this.clearReconnectTimer();
    const readyState = this.ws?.ws?.readyState;
    if (readyState === WebSocket.OPEN || readyState === WebSocket.CONNECTING) {
      return;
    }
    this.connectCount++;
    this.ws = new WS({
      url: `ws-weapp.xjiangiot.com/websocket?token=${getUrlQueryString("token")}`,
      protocol: [],
      onOpen: (ws: WS, ev: Event) => {
        this.setState("status", { pageConnectState: true });
        // WebSocket 连上后批量发出缓存的消息
        while (this.pendingSend.length) {
          const msg = this.pendingSend.shift()!;
          this.ws.send(msg);
        }
      },
      onMessage: (ws: WS, ev: MessageEvent) => {
        console.log("onMessage=", ev.data);
        if (ev.data instanceof Blob) {
          const reader = new FileReader();
          reader.onload = event => {
            const data = event.target?.result;
            console.log("接受数据转回string=", data);
            const _d = JSON.parse(`${data}`);
            console.log("_d=", _d);
            this.onMessage(_d);
          };
          reader.readAsText(ev.data); // 读取blob内的数据
        } else {
          const _d = JSON.parse(ev.data);
          console.log("_d=", _d);
          this.onMessage(_d);
        }
      },
      onError: () => {
        // websocket连接失败，重连，重连3次失败，给用户反馈提示
        if (this.connectCount > 3) {
          this.connectCount = 0;
          this.setState("status", { pageConnectState: false });
        } else {
          this.scheduleReconnect();
        }
      },
      onClose: () => {
        if (this.isPageVisible) {
          this.setState("status", { pageConnectState: false });
        }
      }
    });
    this.popupLoading && this.popupLoading.close();
    if (this.shouldShowConnectLoading) {
      this.popupLoading = loading({
        type: "loading",
        text: "加载中...",
        canDismiss: false
      });
    }
    this.shouldShowConnectLoading = true;
  }

  /**** 初始化 插件 **/
  initProject() {
    /**** 初始化 **/
    if (this.config.type == "ble" && !this.bleJson) {
      this.getProtocol().then(() => this.initLoop());
    } else {
      this.initLoop();
    }
  }
  initLoop() {
    /**** 初始化 **/
    if (this.config.type == "ble") {
      this.webSocketSend("onPageInit", { protocol: this.bleJson });
      this.connectCount = 0;
      // this.setState("status", { pageConnectState: true });

      // 初始化项目，自动连接蓝牙
      this.device.bleConnect();
    } else {
      this.webSocketSend("onPageInit");
    }
  }
  //#endregion

  constructor(config: ConfigType) {
    super();
    // 导入本地协议
    if (config?.data) {
      this.protocolConfig = handleConfig2Protocol(config?.data);
    }
    if (getUrlQueryString("name")) {
      document.title = getUrlQueryString("name");
    }
    super.initConfig(config);
    // 将 WeappApi 实例挂到 window.xj 上，供 nativeApiRequestHeaders 发送消息
    const gxj = ((window as any).xj = (window as any).xj || {});
    gxj._weappApi = this;
    this.bindLifecycleEvents();
    this.initWS();
  }

  //#region 初始化
  /***
   * 初始化项目，用于整理整体数据和信息
   */
  initDevice(callbacks: PageFuncType) {
    super.initData(callbacks);
  }

  /***
   * 初始化页面，每个页面单独处理
   */
  pageInit(callbacks: PageFuncType) {
    super.initPageData(callbacks);
  }

  /***
   * 退出websocket连接/页面数据监听
   */
  exitPage() {
    this.unbindLifecycleEvents();
    this.clearReconnectTimer();
    this.ws.closure();
    this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
    this.bleConnectTimer && clearTimeout(this.bleConnectTimer);
  }

  /***
   * 退出H5页面
   */
  exit() {
    this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
    this.webSocketSend("exit");
    this.exitPage();
  }

  /***
   * 刷新页面
   */
  reload() {
    this.exitPage();
    window.location.reload();
  }

  /***
   * 本地更改数据，不下发
   */
  setAttrs(data) {
    if (data && Object.keys(data) && Object.keys(data).length) {
      this.setState("data", { ...this.states.data, ...(data ?? {}) });
    }
  }

  /** 通过不同的key获取 data、info 的全部属性，一般可以用于初始化页面数据 */
  setState(key: TStateKey, state: object): any {
    super.setState(key, state);
  }
  /**
   * 获取数据
   * @param key
   * @returns
   */
  getState(key: TStateKey): object {
    return super.getState(key);
  }
  //#endregion

  //#region 设备相关
  private bleConnectTimer: any;

  device = {
    data: {},
    info: {},
    /***
     * 获取设备信息
     */
    getDeviceInfo: () => {
      this.webSocketSend("getDeviceInfo", null);
    },

    /***
     * 获取设备快照
     * @params keys: ["PowerSwitch"]
     */
    getSnapshot: () => {
      this.webSocketSend("getDeviceSnapshot", null);
    },

    /***
     * 下发属性
     * @params params  { 'key': value, updateTime?: number }
     *  {"method":"deviceDataSet","params":{"key":"prop.3.1","value":0}}
     */
    set: (datas: object, okStates?: object, updateTime?: number) => {
      return new Promise((resolve, reject) => {
        if (!datas || !Object.keys(datas) || !Object.keys(datas).length) {
          return reject();
        }

        let _params = {},
          _pKey = [],
          _pVal = [];
        for (const k in datas) {
          _pKey = [...(_pKey || []), k];
          _pVal = [...(_pVal || []), datas[k]];
        }

        if (_pKey.length > 1) {
          _params = {
            keys: _pKey,
            values: _pVal
          };
        } else if (_pKey.length === 1) {
          _params = {
            key: _pKey[0],
            value: _pVal[0]
          };
        }
        let _sKey: string[] = [];
        if (okStates) {
          _sKey = Object.keys(okStates);
        }
        _params = {
          ..._params,
          result: res => {
            // 下发异常处理----固定异常提示
            // todo
            resolve(res);
          }
        };

        if (
          (!("key" in _params) && !("keys" in _params)) ||
          !this.config?.data
        ) {
          return reject();
        }

        this.IgnoreAttrs = [...this.IgnoreAttrs, ..._pKey, ..._sKey];
        this.IgnoreAttrs = Array.from(new Set(this.IgnoreAttrs)); // 去重
        // 预先页面渲染
        this.setState("data", { ...this.states.data, ...(datas ?? {}) });

        if (isDebug) {
          // 在isdebug下，setTimeout模拟设备的回馈操作
          this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
          this.SetSyncTimer = setTimeout(() => {
            this.setState("data", { ...this.states.data, ...(datas ?? {}) });
            return resolve(datas);
          }, 300);
        } else {
          let _paramsSet = JSON.parse(JSON.stringify(_params));
          if ("key" in _paramsSet) {
            const _pKey = handleProtocol2Key(
              [_paramsSet?.key],
              this.config.data
            );
            _paramsSet = {
              ..._paramsSet,
              key: _pKey && _pKey.length ? _pKey[0] : _paramsSet.key
            };
          } else if ("keys" in _paramsSet) {
            _paramsSet = {
              ..._paramsSet,
              keys: handleProtocol2Key(_paramsSet?.keys, this.config.data)
            };
          }

          this.webSocketSend("deviceDataSet", JSON.stringify(_paramsSet));

          this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
          this.SetSyncTimer = setTimeout(() => {
            this.device.get(
              handleProtocol2Key(this.IgnoreAttrs, this.config.data)
            );
            this.IgnoreAttrs = [];
          }, updateTime || 3000);
        }
      });
    },

    /***
     * 获取数据
     * @params keys: ["PowerSwitch"]
     */
    get: (keys: string[]) => {
      return new Promise((resolve, reject) => {
        // if (!keys || !keys.length || typeof keys !== "object") {
        //   return reject();
        // }
        console.log("get---->", keys);
        this.webSocketSend("deviceDataGet", JSON.stringify(keys ?? []));
      });
    },

    /***
     * 蓝牙设备连接
     */
    bleConnect: () => {
      this.setState("status", { bleConnectState: 2 });
      this.webSocketSend("connect");

      // 连接超时  30s超时弹窗提示
      this.bleConnectTimer && clearTimeout(this.bleConnectTimer);
      this.bleConnectTimer = setTimeout(() => {
        this.device.bleDisConnect();
      }, 30000);
    },
    /***
     * 蓝牙设备断开连接
     * @param type
     */
    bleDisConnect: (type?: number) => {
      if (!type) {
        this.setState("status", { bleConnectState: 0 });
      }
      this.webSocketSend("disconnect");
    },
    /***
     * 蓝牙重连
     */
    reconnect: () => {
      this.device.bleDisConnect(1);
      setTimeout(() => {
        this.device.bleConnect();
      }, 200);
    }
  };
  //#endregion

  //#region nav
  /***
   *
   */
  setNavigationBarTitle(title: string) {}
  setNavigationBarTintColor(color: string) {}
  setNavigationBarBackgroundColor(color: string) {}

  setNavigationBarLeftButton(buttons: NavButtons) {}
  setNavigationBarRightButton(buttons: NavButtons) {}

  setNavigationBarStyle(type: number) {}

  /***
   * 跳转通用设置界面
   */
  openSettingsPage() {
    this.webSocketSend("openSettingsPage");
  }

  //#endregion

  //#region ota
  /***
   * OTA 信息
   */
  otaInfo: OtaInfoType | undefined;

  /***
   * OTA 强制升级弹窗
   * **展示强制升级的弹窗，如不需要自定义强制升级的页面，可以使用此方法
   */
  showForceUpgradeModalIfNeed() {}
  /***
   * OTA 升级
   * @params
   */
  ota(params: OtaParamsType) {}
  //#endregion
}
