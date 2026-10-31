import { proxyHandler } from '../utils';
import type { ConfigType, TStateKey, PageFuncType } from '../utils/type.d.ts';

export default class Data {
  /** 回调监听(设备属性) */
  protected _onCallbacks: Map<any, PageFuncType> = new Map();
  protected _onPageCallbacks: Map<any, PageFuncType> = new Map();

  protected initData(callbacks: PageFuncType) {
    const key = "XJ_INIT_" + new Date().getTime();
    this._onCallbacks.set(key, callbacks);
  }
  protected initPageData(callbacks: PageFuncType) {
    const _key: string = !callbacks?.key ? "XJ_" + new Date().getTime() : (callbacks?.key || "");
    this._onPageCallbacks.set(_key, callbacks);
  }

  protected config: ConfigType = {
    type: "wifi", // ble  |  wifi
    shouldWaitTo_getSnapshot: false
  }
  
  /**
   * 【初始化】 初始化配置信息
   * @param config {Object} 设备属性
   */
  protected initConfig(config?: ConfigType): void {
    /* 合并默认配置 */
    if (config) {
      this.config = config;
    }

    // ----弃用----
    // if (config?.type == 'ble') {
    //   this.getProtocol();
    // }
  }

  // 数据
  protected states = {
    /**
     * 设备信息
     */
    info: new Proxy({}, proxyHandler(this._notify('info'))) as object,
    /**
     * 设备数据
     */
    data: new Proxy({}, proxyHandler(this._notify('data'))) as object,

    /**
     * 状态
     * bleState  蓝牙状态    0：未知；  1：不可用；   2：未授权；   3：未打开；   4：可用
     * bleConnectState  蓝牙设备连接状态    0：未连接；  1：正在连接；  2：已连接； 3：正在搜索；(待定)    4：就绪 (待定)
     * pageConnectState 页面websocket连接状态
     * getDeviceSnapshot 页面数据状态---快照获取完成
     */
    status: new Proxy({ bleState: 0, bleConnectState: 0, pageConnectState: true, getDeviceSnapshot: false }, proxyHandler(this._notify('status'))) as object,

    /**
     * 初始化信息
     */
    init: new Proxy({ }, proxyHandler(this._notify('init'))) as object
  };

  /** 通过不同的key获取 data、status、native 或 device 的全部属性，一般可以用于初始化页面数据 */
  protected getState(key: TStateKey): object {
    return this.states[key];
  }

  /** 通过不同的key设置 data、status、native 或 device 的全部属性，一般可以用于初始化页面数据 */
  protected setState(key: TStateKey, state: object | null): object {
    return Object.assign(this.states[key], state || {})
  }

  /**【回调监听】 删除属性改变的回调 */
  protected removeCallback(key: any): void {
    this._onCallbacks.delete(key);
  }
  /**【回调监听】 删除属性改变的回调 */
  protected removePageCallback(key: any): void {
    this._onPageCallbacks.delete(key);
  }

  /**【结束】运行结束，停止所有监听，定时 */
  protected end(): void {
    this._onCallbacks.clear();
    this._onPageCallbacks.clear();
  }

  /**
   * 通知回调函数
   * @param key 通知类型
   */
  private _notify(key: TStateKey) {
    return (state: any) => {
      switch (key) {
        case 'data':
          const _data = { ...state, ...this.states.data };
          this._onCallbacks.forEach(({ onDeviceDataChange }) => {
            onDeviceDataChange && onDeviceDataChange(_data);
          });
          this._onPageCallbacks.forEach(({ onDeviceDataChange }) => {
            onDeviceDataChange && onDeviceDataChange(_data);
          });
          break;
        case 'info':
          const _info = { ...state, ...this.states.info };
          this._onCallbacks.forEach(({ onDeviceInfoChange }) => {
            onDeviceInfoChange && onDeviceInfoChange(_info);
          });
          this._onPageCallbacks.forEach(({ onDeviceInfoChange }) => {
            onDeviceInfoChange && onDeviceInfoChange(_info);
          });
          break;
        case 'status':
          this._onCallbacks.forEach(({ onBleStateChange, onBleConnectStateChange, onPageConnectChange, onDataStateChange }) => {
            if ('bleState' in state) {
              onBleStateChange && onBleStateChange(state?.bleState);
            }
            if ('bleConnectState' in state) {
              onBleConnectStateChange && onBleConnectStateChange(state?.bleConnectState);
            }
            if ('pageConnectState' in state) {
              onPageConnectChange && onPageConnectChange(state?.pageConnectState);
            }
            if ('getDeviceSnapshot' in state) {
              onDataStateChange && onDataStateChange(state?.getDeviceSnapshot);
            }
          });
          
          this._onPageCallbacks.forEach(({ onBleStateChange, onBleConnectStateChange, onPageConnectChange, onDataStateChange }) => {
            if ('bleState' in state) {
              onBleStateChange && onBleStateChange(state?.bleState);
            }
            if ('bleConnectState' in state) {
              onBleConnectStateChange && onBleConnectStateChange(state?.bleConnectState);
            }
            if ('pageConnectState' in state) {
              onPageConnectChange && onPageConnectChange(state?.pageConnectState);
            }
            if ('getDeviceSnapshot' in state) {
              onDataStateChange && onDataStateChange(state?.getDeviceSnapshot);
            }
          });
          break;
        case 'init':
          this._onCallbacks.forEach(({ onPageInit }) => {
            onPageInit && onPageInit(state)
          });
          break;
      }
    };
  }


  /***
   * ble JSON-----弃用
   */
  protected bleJson: any;
  protected deviceJson: any;
  /****
   * 获取本地协议
   */
  protected getProtocol() {
    return new Promise((resolve, reject) => {
      this.getFile(0, "device").then(res => {
        this.deviceJson = res;
        this.getFile(1, "ble").then(res => {
          if (this.deviceJson?.type == 'ble') {
            console.log('传入蓝牙本地协议');
            this.bleJson = res
            resolve(res);
            // this.webSocketSend("importProtocol", this.bleJson);
          } else {
            console.log('');
            reject("error")
          }
        }, _ => reject(_));
      }, _ => reject(_));
    })
  }
  /***
   * 获取本地文件
   */
  protected getFile(type: number, url: string) {
    return new Promise((resolve, reject) => {
      // import(!type ? "@/config/device" : "@/config/ble").then((res) => {
      //   if (res && res.default) {
      //     console.log("获取文件成功", url, res)
      //     resolve(res?.default);
      //   } else {
      //     reject("")
      //     console.error("获取文件错误", url, "")
      //   }
      // }, _ => {
      //   reject(_)
      //   console.error(`获取${url}文件错误，请重新配置`)
      // })
    });
  }
}