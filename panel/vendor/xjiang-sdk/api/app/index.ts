
import Data from '../data';
import type { ConfigType, TStateKey, PageFuncType, BleResultType } from '../../utils/type.d.ts';
import { xj } from './XJIotApi';

const isDebug = import.meta.env?.MODE === "debug"; // 是否开启调试模式

const METHOD_NAME = {
  deviceDataSet: 'deviceDataSet',
  deviceBleConnect: 'deviceBleConnect',
  deviceBleDisConnect: 'deviceBleDisConnect',
  deviceGet: 'deviceDataGet',
  deviceGetSnapshot: 'deviceDataGetSnapshot',
  
  navigationTo: "navigationTo",
  hidePicker: "hidePicker",
  hideToast: "hideToast",
  showToast: "showToast",
  openSettingsPage: "openSettingsPage",
  setNavigationBarTitle: "setNavigationBarTitle",
  showPicker: "showPicker",
  showAlert: "showAlert",
  setNavigationBarButton: "setNavigationBarButton",

  onGetStatusBarHeight: "onGetStatusBarHeight",
  onDeviceOnline: "onDeviceOnline",
  showNavigationBar: "showNavigationBar",
  hideNavigationBar: "hideNavigationBar",

  configGet: "configGet",
  configSet: "configSet",
  configMerge: "configMerge",
  configDelete: "configDelete"
}

export default class AppApi extends Data {
  protocol = xj.protocol; // 设备协议
  protocolConfig = { data: {}, protocol: {}, protocolKeys: {} }; // 设备协议转换成内部格式
  SetSyncTimer: NodeJS.Timeout;
  IgnoreAttrs: string[] = [];

  xj: any = {
    /** 开始业务逻辑 **/
    bleState: xj.bleState,
    bleConnectState: xj.bleConnectState,
    isDarkMode: xj.isDarkMode,
    /*** 多语言 */
    strings: xj.strings,
    languageCode: xj.languageCode
  };

  constructor(config: ConfigType) {
    super();
    // 导入本地协议
    if (config?.data) {
      this.protocolConfig = this.handleConfig2Protocol(config?.data);
      this.protocol = this.protocolConfig?.protocol;
    }
    this.init(config);
    super.initConfig(config);
  }

  /** 通过不同的key获取 data、info 的全部属性，一般可以用于初始化页面数据 */
  setState(key: TStateKey, state: object): any {
    super.setState(key, state);
  }
  getState(key: TStateKey): object {
    return super.getState(key);
  }

  /***
   * 初始化项目，用于整理整体数据和信息
   */
  initDevice(callbacks: PageFuncType) {
    super.initData(callbacks);

    // 获取状态栏高度
    xj.getStatusBarHeight();

    // 获取设备状态
    xj.getDeviceOnline();

    if (this.config.type == 'ble') {
      console.log('需要跑蓝牙')
      // 初始化项目，自动连接蓝牙
      this.xj.device.bleConnect({
        result: (res: BleResultType) => {
          console.log('bleConnect---result-->', res)
          // 连接成功
          if (!!res.errorCode) {
            this.setState("status", { bleConnectState: 0 });
          } else {
            // 常规组件 需要进入页面就快照
            if (this.config.shouldWaitTo_getSnapshot) {
              setTimeout(() => {
                this.xj.device.getSnapshot({})
              }, 2000)
            } else {
              console.log('正常快照')
              this.xj.device.getSnapshot({})
            }
          }
        },
      });
    }
  }

  /***
   * 初始化页面，每个页面单独处理
   */
  pageInit(callbacks: PageFuncType) {
    xj.pageInit(callbacks);
    super.initPageData(callbacks);
  }

  /**
   * 数据统一处理
   */
  init(config: ConfigType) {
    this.xj = {
      ...this.xj,

      /* 本地配置 */
      config: { // 本地存储相关操作
        /**
         * 获取本地缓存 get
         * @param params  strings[]
         * @returns 
         */
        get: (params) => {
          return new Promise((resolve, reject) => {
            const _params = {
              keys: params,
              result: (res) => {
                if (res.ok) {
                  resolve(res.config)
                } else {
                  reject()
                }
              }
            }
            // this.handleCallBackParams(params, 'result')
            this.msgToNative(METHOD_NAME['configGet'], _params, 'result')
          });
        },
        /**
         * 本地存储 set
         * @param params { key: string, value: string } 
         */
        set: (params) => {
          return new Promise((resolve, reject) => {
            const _params = {
              ...params,
              result: (res) => {
                if (res.ok) {
                  resolve(res)
                } else {
                  reject()
                }
              }
            }
            // this.handleCallBackParams(params, 'result')
            this.msgToNative(METHOD_NAME['configSet'], _params, 'result')
          });
        },
        /**
         * 合并存储
         * @param params { name: 'Renge', time: 0 }
         * @returns 
         */
        merge: (params) => {
          return new Promise((resolve, reject) => {
            const _params = {
              data: params,
              result: (res) => {
                if (res.ok) {
                  resolve(res)
                } else {
                  reject()
                }
              }
            }
            // this.handleCallBackParams(params, 'result')
            this.msgToNative(METHOD_NAME['configMerge'], _params, 'result')
          });
        },
        /**
         * 删除本地存储
         * @param params  string | string[]
         * @returns 
         */
        delete: (params) => {
          return new Promise((resolve, reject) => {
            const _params = {
              key: params,
              result: (res) => {
                if (res.ok) {
                  resolve(res)
                } else {
                  reject()
                }
              }
            }
            // this.handleCallBackParams(params, 'result')
            this.msgToNative(METHOD_NAME['configDelete'], _params, 'result')
          });
        }
      },

      device: { 
        info: {},
        data: {},
        oData: {},
        /**
         * 下发设备数据 set
         * @params params  { 'key': value } 
         * @param okStates { 'key': value }  // 联动 控制其他属性先更新状态
         * @params updateTime 同步数据时间，默认3000ms
         * */ 
        set: async (params, okStates, updateTime = 3000) => {
          return new Promise(async (resolve, reject) => {
            if (!params || !this.protocol) {
              return reject();
            }
  
            let _params = { }, _pKey = [], _pVal = [];
            for (const k in params) {
              _pKey = [...(_pKey || []), k]
              _pVal = [...(_pVal || []), params[k]]
            }

            if (_pKey.length > 1) {
              _params = { 
                keys: _pKey,
                values: _pVal
              }
            } else if (_pKey.length === 1) {
              _params = { 
                key: _pKey[0],
                value: _pVal[0]
              }
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
                resolve(res)
              }
            };
  
            if ((!('key' in _params) && !('keys' in _params)) || !this.protocol) {
              return reject();
            }
            this.IgnoreAttrs = [...this.IgnoreAttrs, ..._pKey, ..._sKey];
            this.IgnoreAttrs = Array.from(new Set(this.IgnoreAttrs)); // 去重
            
            // 预先页面渲染
            this.xj.device.data = { ...this.xj.device.data, ...params, ...(okStates || {}) }
            this.setState("data", this.xj.device.data);

            if (isDebug) {
              // 在isdebug下，setTimeout模拟设备的回馈操作
              console.log('isDebug-set-->', METHOD_NAME["deviceDataSet"] + ', params-->' + JSON.stringify(params), _params)

              this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
              this.SetSyncTimer = setTimeout(() => {
                if (params) {
                  this.xj.device.data = { ...this.xj.device.data, ...params }
                } else {
                  return
                }
                this.setState("data", this.xj.device.data);
                return resolve(params)
              }, 1000)
            } else {
              // this.handleCallBackParams(params, 'result')
              let _paramsSet = JSON.parse(JSON.stringify(_params))
              if ('key' in _paramsSet) {
                const _pKey = this.handleProtocol2Key([_paramsSet?.key]);
                _paramsSet = {
                  ..._paramsSet,
                  key: _pKey && _pKey.length ? _pKey[0] : _paramsSet.key
                }
              } else if ('keys' in _paramsSet) {
                _paramsSet = {
                  ..._paramsSet,
                  keys: this.handleProtocol2Key(_paramsSet?.keys)
                }
              }

              this.msgToNative(METHOD_NAME["deviceDataSet"], _paramsSet, 'result');

              this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
              this.SetSyncTimer = setTimeout(() => {
                this.xj.device.get(this.IgnoreAttrs);
                this.IgnoreAttrs = [];
              }, updateTime || 3000);
            }
          }).catch(err => {
            console.log('set-error->', err)
          });
        },
  
        /**
         * 获取设备数据 get
         * @params params  ["powerswitch"]  string[]
         * */ 
        get: (params) => {
          return new Promise(async (resolve, reject) => {
            if (!params || !this.protocol) {
              return reject();
            }

            // let _allKeys = params || [];
            // if (!params || !params.length) {
            //   try {
            //     if (this.protocol) {
            //       _allKeys = Object.keys(this.protocol);
            //     }
            //   } catch(e) { }
            // }

            let _params: any = params && params.length ? { keys: this.handleProtocol2Key(params) } : {};
            _params = {
              ..._params,
              result: res => resolve(res)
            };

            // if (
            //   _params.length &&
            //   (!_params?.keys ||
            //     !Object.keys(_params?.keys) ||
            //     !Object.keys(_params?.keys).length ||
            //     !this.protocol)
            // ) {
            //   return reject();
            // }

            console.log(params, _params)
            if (isDebug) { 
              // 在isdebug下，setTimeout模拟设备的回馈操作
              setTimeout(() => {
                // eslint-disable-next-line prefer-const
                let values = [];
                console.log("isDebug---->", _params)
                if (_params?.keys) {
                  for (const name of _params.keys) {
                    const value = this.xj.device.data[name]
                    values.push({ value, code: 0 })
                  }
                } else {
                  _params.result({
                    errorCode: -1,
                    msgId: 0
                  })
                  return reject();
                }
                this.setState("data", this.xj.device.data);
                return resolve(_params)
              }, 1000)
            } else {
              this.msgToNative(METHOD_NAME["deviceGet"], _params, 'result')
            }
          }).catch(err => {
            console.log('get-error->', err)
          });
        },
        // 获取设备快照 getSnapshot
        getSnapshot: (params) => {
          if (isDebug) { 
            // 在isdebug下，setTimeout模拟设备的回馈操作
            setTimeout(() => {
              params.result({
                msgId: 0,
                errorCode: 0,
                data: this.xj.device.data,
              })
            }, 1000)
          } else { 
            this.msgToNative(METHOD_NAME["deviceGetSnapshot"], params, 'result')
          }
        },
        // 蓝牙设备连接 bleConnect
        bleConnect: (params) => {
          if (isDebug) { 
            // 在isdebug下，setTimeout模拟设备的回馈操作
            setTimeout(() => {
              params['result']({ 
                isSucceed: true,
                errorCode: 0
              })
            }, 1000)
          } else {
            // this.handleCallBackParams(params, 'result')
            this.msgToNative(METHOD_NAME["deviceBleConnect"], params, 'result')
          }
        },
        // 蓝牙设备断开连接 bleDisConnect
        bleDisConnect: () => {
          this.msgToNative(METHOD_NAME["deviceBleDisConnect"])
        }
      },
      
      // 初始化设备
      initDevice: (device) => { 
        if (config?.basicConfig?.defaultData) {
          // 默认初始值，默认开启
          this.xj.device.data = this.protocolConfig?.data;
          this.setState("data", this.xj.device.data);
        }

        device.oData = device.data
        const data = this.attrIdDataToNamedata(device.oData)
        device.data = data
        xj.combindMap(this.xj.device, device)
        this.setState("info", this.xj.device.info);
        this.setState("data", this.xj.device.data);
      },
      onDeviceInfoChange: (info) => {
        this.xj.device.info = info
        this.setState("info", this.xj.device.info);
      },
      onDeviceDataChange: (data) => {
        let _newData = {};
        if (this.IgnoreAttrs) {
          for (const k in data) {
            if (!this.IgnoreAttrs.includes(k)) {
              _newData = { ..._newData, [`${ k }`]: data[k] };
            }
          }
        } else _newData = data;
        this.xj.device.data = this.handleProtocol2Value(_newData)
        this.setState("data", this.xj.device.data);
      },
      onGetDarkMode: (isDarkMode) => {
        this.xj.isDarkMode = isDarkMode;
      },
      onDeviceStatusChange: (status) => {
        this.setState("status", status);
      }
    }
    
    xj.initDevice = (device) => {
      this.xj.initDevice(device);
    }
    xj.onDeviceInfoChange = (info) => {
      this.xj.onDeviceInfoChange(info);
    }
    xj.onDeviceDataChange = (data) => {
      this.xj.onDeviceDataChange(data);
    }
    xj.onDeviceStatusChange = (status) => {
      console.log("xj.onDeviceStatusChange-->", status)
      this.xj.onDeviceStatusChange(status);
    }
    xj.onGetDarkMode = (isDarkMode) => {
      this.xj.onGetDarkMode(isDarkMode);
    }
    xj.stringsInit = (codeObj) => {
      this.xj.languageCode = codeObj?.code || "zh-CN";
      this.setState("init", { languageCode: this.xj.languageCode, initComplete: true })
    }
    
    // 监听深色模式
    xj.onGetDarkMode = (isDarkMode) => {
      this.xj.onGetDarkMode(isDarkMode);
    }
    
    // 状态高度
    xj.onGetStatusBarHeight = (v) => {
      this.setState("init", { statusBarHeight: v?.statusBarHeight || 24 })
    }
    
    // 监听设备状态 --- 导致白屏先注释
    // xj.onDeviceOnline = (v) => {
    //   console.log("onDeviceOnline---->",v)
    //   this.setState("init", { isOnline: v ?? false })
    // }
  };
  
  /***
   * 退出H5页面
   */
  exit() {
    this.SetSyncTimer && clearTimeout(this.SetSyncTimer);
    if (this.config.type == 'ble') {
      console.log('需要跑蓝牙')
      this.xj.device.bleDisConnect({});
    } else {
      console.log('不需要跑蓝牙')
    }
  }

  /***
   * 本地更改数据，不下发
   */
  setAttrs(data) {
    if (data && Object.keys(data) && Object.keys(data).length) {
      this.xj.device.data = { ...this.xj.device.data, ...data };
      this.setState("data", this.xj.device.data);
    }
  }

  //#region 设备协议
  importProtocol(protocol: any) { // 传参导入protocol设备协议(不传默认为{}),可以自动完成蓝牙设备数据的 name 和 attrId 转换，下发和上报只需要关心属性名称即可
    if (!protocol) { protocol = {} }
    this.protocol = protocol
    if (this.xj.device.oData) {
      this.xj.device.data = this.attrIdDataToNamedata(this.xj.device.oData)
    }
    // xj.importProtocol(protocol);
    console.log('~~~~~~~~~~~~~~~~~~~~~protocol=', this.protocol)
  }
  addProtocol(protocol) { // 检测新传入的protocol，和xj.protocol不同，则合并到xj.protocol中
    if (protocol && !this.protocol) {
      this.protocol = protocol
    } else {
      xj.combindMap(this.protocol, protocol)
      this.protocol = { ...this.protocol }
    }
    if (this.xj.device.oData) {
      this.xj.device.data = this.attrIdDataToNamedata(this.xj.device.oData) // 然后根据新的protocol，再对data做一次键名转化
    }
  }
  //#endregion

  //#region 数据处理
  handleProtocol2Value(values) {
    let keyVals = {};
    if (values) {
      for (const v in values) {
        if (this.protocolConfig && this.protocolConfig?.protocolKeys) {
          const _keys = this.protocolConfig?.protocolKeys;
          if (v in _keys) {
            keyVals = { ...keyVals, [`${ _keys[v] }`]: values[v] }
          }
        }
      }
    }
    return keyVals;
  }
  handleConfig2Protocol(config) {
    let _c = {}, _d = {}, _k = {};
    if (config) {
      for (const k in config) {
        if (k && config[k]) {
          _c = { ..._c, [`${ k }`]: { key: config[k]?.key } }
          _d = { ..._d, [`${ k }`]: config[k]?.value }
          _k = { ..._k, [`${ config[k]?.key }`]: k }
        }
      }
    }
    return { protocol: _c, data: _d, protocolKeys: _k };
  }
  handleProtocol2Key(keys: string[]) {
    if (!keys || !keys.length) return null;

    let propKeys = [];
    if (this.protocol) {
      for (const k of keys) {
        if (k in this.protocol) {
          const _propKey = this.protocol[k];
          if (_propKey?.key) {
            propKeys = [...propKeys, _propKey?.key]
          } else {
            propKeys = [...propKeys, k]
          }
        } else {
          propKeys = [...propKeys, k]
        }
      }
    }
    return propKeys;
  }
  

  attrIdDataToNamedata(attrIdData) { // 传入的data，根据protocol设备协议，将键名转化为name，例如'0x01'转化为'powerstate'
    attrIdData = { ...attrIdData }
    if (!this.protocol) {
      return attrIdData
    }
    for (const attrId in attrIdData) {
      if (Object.hasOwnProperty.call(attrIdData, attrId)) {
        const value = attrIdData[attrId]
        const protocol = this.protocol[attrId]
        if (protocol) {
          delete attrIdData[attrId]
          attrIdData[protocol.name] = value
        }
      }
    }
    return attrIdData
  }

  /*** 
   * 封装JS到原生的消息发送，区别 iOS 和 android
  */
  msgToNative(method: string, params?: any, callbackKey?: any, uuid?: any) {
    if (isDebug) {
      console.log(method, params)
      return
    }
    (params && callbackKey) && this.handleCallBackParams(params, callbackKey, uuid);
    xj.msgToNative(method, params);
  }
  
  /*
  处理H5 Api 需要返回值的函数
  params 为函数的参数
  callbackKey 为 params 对应的回调函数的 key
  uuid 为指定的回调对应的 uuid, 不传则随机生成
  */
  handleCallBackParams(params: any, callbackKey?: any, uuid?: any) {
    xj.handleCallBackParams(params, callbackKey, uuid);
  }
  //#endregion

  //#region native
  setNavigationBarButton(params) {
    let i = 0
    for (const value of params) {
      this.handleCallBackParams(value, 'action', 'navigationBarAction_' + i)
      i++
    }
    this.msgToNative(METHOD_NAME['setNavigationBarButton'], params)
  }
  showAlert(dic) {
    // this.handleCallBackParams(dic, 'result')
    this.msgToNative(METHOD_NAME['showAlert'], dic, 'result')
  }
  showPicker(dic) {
    // this.handleCallBackParams(dic, 'result')
    this.msgToNative(METHOD_NAME['showPicker'], dic, 'result')
  }
  setNavigationBarTitle(title) {
    this.msgToNative(METHOD_NAME['setNavigationBarTitle'], title)
  }
  openSettingsPage(params) {
    this.msgToNative(METHOD_NAME['openSettingsPage'], params)
  }
  showToast(dic) {
    this.msgToNative(METHOD_NAME['showToast'], dic)
  }
  hideToast(dic) {
    this.msgToNative(METHOD_NAME["hideToast"], dic)
  }
  showNavigationBar() {
    this.msgToNative(METHOD_NAME["showNavigationBar"])
  }
  hideNavigationBar() {
    this.msgToNative(METHOD_NAME["hideNavigationBar"])
  }
  navigationTo(path, params) {
    const msg = params ? [path, params] : path
    this.msgToNative(METHOD_NAME["navigationTo"], msg)
  }
  //#endregion
};