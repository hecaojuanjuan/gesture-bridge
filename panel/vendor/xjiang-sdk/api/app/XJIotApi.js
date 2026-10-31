/* eslint-disable */
import WS from "../weapp/webSocket";
import { getUrlQueryString } from "../../utils";

const xj_that = window; // ----------------------------------------------------------------------------------------- 向window全局添加对象xj
const deviceDataSet = "deviceDataSet";
const deviceBleConnect = "deviceBleConnect";
const deviceBleDisConnect = "deviceBleDisConnect"; // -------------------------------------------------------------- 变量赋值，方便改名？
const deviceGet = "deviceDataGet";
const deviceGetSnapshot = "deviceDataGetSnapshot";
const onPageInit = "onPageInit";

const isMiniProgramEnv =
  window.__wxjs_environment === "miniprogram" ||
  (typeof window.__wxjs_environment === "undefined" &&
    /MicroMessenger/i.test(navigator.userAgent));

let ws; // -------------------------------------------------------------------------------------------------------- 全局变量，用于存储websocket实例
let wsConnected = false;
let wsConnectCount = 0;
const wsQueue = [];
const initWS = () => {
  ws = new WS({
    url: `ws_weapp.xjiangiot.com/websocket?token=${getUrlQueryString("token")}`,
    protocol: [],
    onOpen: () => {},
    onMessage: (ws, ev) => {
      console.log("onMessage=", ev.data);
      if (ev.data instanceof Blob) {
        const reader = new FileReader();
        reader.onload = event => {
          const data = event.target?.result;
          console.log("接受数据转回string=", data);
          onMessageEvent({ data });
        };
        reader.readAsText(ev.data); // 读取blob内的数据
      } else {
        onMessageEvent({ data: ev.data });
      }
    },
    onError: () => {
      // websocket连接失败，重连，重连3次失败，给用户反馈提示
      if (wsConnectCount > 3) {
        wsConnectCount = 0;
        xj.onDeviceStatusChange({ pageConnectState: false });
      } else {
        setTimeout(() => {
          initWS();
        }, 50);
      }
    }
  });
};

/** 监听来自Native的消息 */
const onMessageEvent = event => {
  const msg = event?.data;
  try {
    const { method, params, data } = JSON.parse(msg);

    if (!method) {
      return;
    }

    console.log("[msgFromNative]", msg);

    if (isMiniProgramEnv) {
      if (method === "keepAlive") {
        ws.send(JSON.stringify({ method: "keepAlive_reply", data }));
        // 收到第一次keepAlive后，将wsConnected设置为true，并发送wsQueue中的消息
        if (!wsConnected) {
          wsConnected = true;
          xj.onDeviceStatusChange({ pageConnectState: true });
          while (wsQueue.length) {
            const msg = wsQueue.shift();
            ws.send(msg);
          }
        }
        return;
      }
    }

    if (
      [
        "onLoad",
        "onReady",
        "onShow",
        "onHide",
        "onUnload",
        "onGetDarkMode",
        "onBleStateChange",
        "onBleConnectStateChange",
        // 'onDeviceInfoChange',
        // 'onDeviceDataReport',
        // 'onDeviceDataChange',
        "onOTAInfoChange"
        // 'onGetStatusBarHeight'
      ].includes(method)
    ) {
      xj.page?.[method]?.(params);
    } else {
      xj?.[method]?.(params);
    }
  } catch (error) {}
};
// xj_that.onload = () => {
//   // 开始监听message
//   xj_that.addEventListener('message', onMessageEvent, true);
// };
/** 移除监听message */
const removeMessageEvent = () => {
  xj_that.removeEventListener("message", onMessageEvent);
};

xj_that.xj = {
  pageInit: page => {
    // ---------------------------------------------------------------------------------------- 页面内初始化的方法，传递给xj，代替xj的默认page对象
    console.log("pageInit", page);
    console.log("xj_that", xj_that.xj);

    if (isMiniProgramEnv) {
      initWS();
    } else {
      // 开始监听message
      xj_that.addEventListener("message", onMessageEvent, true);
    }

    xj.page = page;
    xj.msgToNative(onPageInit);
  },

  // 开启调试模式 device.set 调用后会自动上报下发的值
  debug: (fakeDevice, protocol, delay = 500) => {
    // -------------------------------------------------------------- isDebug 开启虚拟设备调试模式,增加了 protocol(设备协议)
    xj.isDebug = true;
    xj.importProtocol(protocol); // -------------------------------------------------------------------------------- 导入protocol设备协议（插件不一定需要导入协议）
    setTimeout(() => {
      xj.initDevice(fakeDevice);
    }, delay);
  },

  // --------------------------------------------------------------------------------------------------------------  protocol 结构如下:
  // example for prorocol
  // key is attrId
  // {
  //   0x01: {
  //     name: 'powerstate',
  //     typeId: 0x00
  //   },
  //   0x0F: {
  //     name: 'Longitude',
  //     typeId: 0x14
  //   }
  // }

  isDebug: false,

  /* 存储回调函数的字典 */
  functionCallbackMap: {}, // ------------------------------------------------------------------------------------- functionCallbackMap 以各guid码，记录返回的回调函数

  /* 随机生成 UUID */
  guid: function () {
    // ------------------------------------------------------------------------------------------ guid()方法，返回随机GUID码
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(
      /[xy]/g,
      function (c) {
        var r = (Math.random() * 16) | 0,
          v = c == "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      }
    );
  },

  /*
  function 换取UUID 并将 function 记录到回调字典
  fun 回调方法
  uuid 为指定的回调对应的 uuid, 不传则随机生成
  */
  functionToUUID: function (fun, uuid = null) {
    // ---------------------------------------------------------------- functionToUUID()方法，传入回调function和guid，记录在对象functionCallbackMap中，返回guid
    if (fun) {
      if (!uuid) {
        uuid = xj.guid();
      }
      xj.functionCallbackMap[uuid] = fun;
    }
    return uuid;
  },

  /*
  处理H5 Api 需要返回值的函数
  params 为函数的参数
  callbackKey 为 params 对应的回调函数的 key
  uuid 为指定的回调对应的 uuid, 不传则随机生成
  */
  handleCallBackParams: function (params, callbackKey, uuid = null) {
    // ------------------------------------------ handleCallBackParams()，记录传入的回调函数（若存在的话），改为在params里标记存储起来后的回调函数的guid
    var callback = params[callbackKey];
    if (callback) {
      uuid = xj.functionToUUID(callback, uuid);
      params["callbackId"] = uuid;
      delete params[callbackKey];
    }
  },

  /* 合并两个字典，a会变化 */
  combindMap: function (a, b) {
    // -------------------------------------------------------------------------------- combindMap() 传入对象a、b, 将b对象中的内容合并到a对象中
    if (!a) {
      return;
    }
    for (const key in b) {
      if (Object.hasOwnProperty.call(b, key)) {
        a[key] = b[key];
      }
    }
  },

  equalMap: function (a, b) {
    // ---------------------------------------------------------------------------------- equalMap() 判断对象ab是否相等 返回bool
    if (a === b) {
      return true;
    }
    if (!a || !b) {
      return false;
    }
    for (const key in a) {
      if (Object.hasOwnProperty.call(a, key)) {
        if (a[key] !== b[key]) {
          return false;
        }
      }
    }
    for (const key in b) {
      if (Object.hasOwnProperty.call(b, key)) {
        if (a[key] !== b[key]) {
          return false;
        }
      }
    }
    return true;
  },

  /* 通过 callbackId 找到function进行回调. params包含 __hold 字段，则移除记录的 function */
  doCallback: function (params) {
    // ------------------------------------------------------------------------------ 承接handleCallBackParams()，若传入的params中已包含callbackId，依此找到库中保存的回调函数，执行回调函数(params)
    let callbackId = params["callbackId"]; // ---------------------------------------------------------------------- 若params中没有__hold 字段，则在回调执行结束后删除 库中保存的回调函数、params中的callbackId
    if (!callbackId) {
      return;
    }
    let callback = xj.functionCallbackMap[callbackId];
    if (!params["__hold"]) {
      delete xj.functionCallbackMap[callbackId];
      delete params["callbackId"];
    }
    if (callback) {
      callback(params);
    }
  },

  /* 封装JS到原生的消息发送，区别 iOS 和 android */
  msgToNative: function (method, params) {
    // --------------------------------------------------------------------- 非调试状态下，根据method函数名来选中ios、android原生方法，并传参执行
    if (xj.isDebug) {
      console.log(method, params);
      return;
    }
    // var u = navigator.userAgent
    // var isAndroid = (u.indexOf('Android') > -1 || u.indexOf('Adr') > -1)
    // var isiOS = !!u.match(/\(i[^;]+;( U;)? CPU.+Mac OS X/)

    // console.log('msgToNative-->', deviceDataSet + ', params-->' + JSON.stringify(params), ', method-->' + method)
    // if (isiOS) {
    //   window.webkit.messageHandlers[method].postMessage(params)
    // } else {
    //   if (params instanceof Object) {
    //     params = JSON.stringify(params)
    //   }
    //   app[method](params)
    // }
    const msg = { method, params };

    console.log("[msgToNative]", JSON.stringify(msg));
    console.log(
      "[env-detect] msgToNative routing | isMiniProgramEnv =",
      isMiniProgramEnv,
      "| wsConnected =",
      wsConnected,
      "| ReactNativeWebView =",
      !!xj_that?.ReactNativeWebView?.postMessage
    );

    if (isMiniProgramEnv) {
      if (wsConnected) {
        ws.send(JSON.stringify(msg));
      } else {
        wsQueue.push(JSON.stringify(msg));
      }
    } else {
      xj_that?.ReactNativeWebView?.postMessage?.(JSON.stringify(msg));
    }
  },

  /** 开始业务逻辑 **/
  bleState: 0,
  bleConnectState: 0,
  strings: {},
  languageCode: "",
  isDarkMode: false,

  device: {
    // ---------------------------------------------------------------------------------------------------- xj.device 拓展 原来只有info、data、set
    info: {},
    data: {},
    oData: {},
    // ------------------------------------------------------------------------------------------------------------ 页面中调用device.set时的传参形式，注意会有个名为result的回调，内容是报出错误信息？
    // xj.device.set({
    //   key: 'PowerState',
    //   value: xj.device.data.PowerState ? 0 : 1,
    //   result: (res) => {
    //     xj.showToast({
    //       title: res.msgId + '\n' + res.succeed + '\n' + res.error,
    //       duration: 5000
    //     })
    //   }
    // })
    // 下发设备数据 set
    set: params => {
      if ((!params.attrId || !params.typeId) && xj.protocol) {
        // ------------------------------------------------- 页面调用device.set时传参params中为key: 'PowerState'，
        for (const attrId in xj.protocol) {
          // -------------------------------------------------------------------- 根据protocol协议，转化添加typeId、attrId到传参params中；
          if (Object.hasOwnProperty.call(xj.protocol, attrId)) {
            const protocol = xj.protocol[attrId];
            if (protocol.name === params.key) {
              if (!params.typeId) {
                params.typeId = protocol.typeId;
              }
              if (!params.attrId) {
                params.attrId = attrId;
              }
            }
          }
        }
      }
      if (xj.isDebug) {
        // ---------------------------------------------------------------------------------------- 在isdebug下，setTimeout模拟设备的回馈操作
        console.log(
          "isDebug-set-->",
          deviceDataSet + ", params-->" + JSON.stringify(params)
        );
        setTimeout(() => {
          if (params.key) {
            // ------------------------------------------------------------------------------------ 根据key、attrId优先级，选一个记录到xj.device.data中
            xj.device.data[params.key] = params.value;
          } else if (params.attrId) {
            xj.device.data[params.attrId] = params.value;
          } else {
            params.result({
              // ------------------------------------------------------------------------------------ params.result 返回操作信息
              errorCode: -1,
              ok: false,
              msgId: 0
            });
            return;
          }
          params.result({
            errorCode: 0,
            ok: true,
            msgId: 0
          });
          xj.page.onDeviceDataChange &&
            xj.page.onDeviceDataChange(xj.device.data); // ----------------------------- 调用页面page的onDeviceDataChange，刷新data
        }, 1000);
      } else {
        // ------------------------------------------------------------------------------------------------- 设备环境下，记录传参中的回调（有的话），转发传参到ios、android的deviceDataSet方法执行
        console.log(
          "set-->",
          deviceDataSet + ", params-->" + JSON.stringify(params)
        );

        xj.handleCallBackParams(params, "result");
        xj.msgToNative(deviceDataSet, params);
      }
    },
    // ------------------------------------------------------------------------------------------------------------ 页面中调用device.get时的传参形式
    // xj.device.get({
    //   keys: ['Switch'],
    //   value: [1],
    //   result: (res) => {
    //     console.log(res.msgId, res.errorCode, res.values[0].key, res.values[0].value);
    //   }
    // });
    // 获取设备数据 get
    get: params => {
      if (!params.attrIds && params.keys && xj.protocol) {
        // ----------------------------------------------------- 根据params的key，给params增加attrId，同时建立了params下所有attrIds的[]
        let attrIds = [];
        for (const name of params.keys) {
          let attrId = xj.__protocolNameToId(name);
          attrIds.push(attrId);
        }
        params.attrIds = attrIds;
      }
      if (xj.isDebug) {
        // ---------------------------------------------------------------------------------------- 在isdebug下，setTimeout模拟设备的回馈操作
        setTimeout(() => {
          let values = [];
          if (params.keys) {
            // ----------------------------------------------------------------------------------- 根据key、attrId的优先顺序，获取value值，建立到values[]
            for (const name of params.keys) {
              let value = xj.device.data[name];
              values.push({ value, code: 0 });
            }
          } else if (params.attrIds) {
            for (const attrId of params.attrIds) {
              let value = xj.device.data[attrId];
              values.push({ value, code: 0 });
            }
          } else {
            params.result({
              errorCode: -1,
              msgId: 0
            });
            return;
          }
          params.result({
            // -------------------------------------------------------------------------------------- 用result回调，传出去values[]
            msgId: 0,
            errorCode: 0,
            values
          });
        }, 1000);
      } else {
        // ------------------------------------------------------------------------------------------------- 设备环境下，记录传参中的回调（有的话），转发传参到ios、android的deviceGet方法执行
        xj.handleCallBackParams(params, "result");
        xj.msgToNative(deviceGet, params);
      }
    },
    // ------------------------------------------------------------------------------------------------------------ 页面中调用device.getSnapshot时的传参形式
    // xj.device.getSnapshot({
    //   result: (res) => {
    //     console.log(res.msgId, res.errorCode, res.data);
    //   }
    // });
    // 获取设备快照 getSnapshot
    getSnapshot: params => {
      if (xj.isDebug) {
        // ---------------------------------------------------------------------------------------- 在isdebug下，setTimeout模拟设备的回馈操作
        setTimeout(() => {
          params.result({
            msgId: 0,
            errorCode: 0,
            data: xj.device.data // ------------------------------------------------------------------------------ 直接用result回调返回去xj.device.data
          });
        }, 1000);
      } else {
        // ------------------------------------------------------------------------------------------------- 设备环境下，记录传参中的回调（有的话），转发传参到ios、android的deviceGetSnapshot方法执行
        xj.handleCallBackParams(params, "result");
        xj.msgToNative(deviceGetSnapshot, params);
      }
    },
    // ------------------------------------------------------------------------------------------------------------ 页面中调用device.bleConnect时的传参形式
    // xj.device.bleConnect({
    //   result: (res) => {
    //     console.log(res.ok, res.errorCode);
    //   }
    // });
    // 蓝牙设备连接 bleConnect
    bleConnect: params => {
      if (xj.isDebug) {
        // ---------------------------------------------------------------------------------------- 在isdebug下，setTimeout模拟设备的回馈操作
        setTimeout(() => {
          params["result"]({
            // ----------------------------------------------------------------------------------- result直接返回固定的结果？
            isSucceed: true,
            errorCode: 0
          });
        }, 1000);
      } else {
        // ------------------------------------------------------------------------------------------------- 设备环境下，记录传参中的回调（有的话），转发传参到ios、android的deviceBleConnect方法执行
        xj.handleCallBackParams(params, "result");
        xj.msgToNative(deviceBleConnect, params);
      }
    },
    // ------------------------------------------------------------------------------------------------------------ 没有传参，直接调用
    // 蓝牙设备断开连接 bleDisConnect
    bleDisConnect: () => {
      xj.msgToNative(deviceBleDisConnect); // ---------------------------------------------------------------------- 设备环境下，调用ios、android的deviceBleDisConnect方法执行
    }
  },

  /* 初始化设备，原生需要在 onLoad 前调用 */
  initDevice: function (device) {
    // ------------------------------------------------------------------------------ 初始化设备
    device.oData = device.data; // --------------------------------------------------------------------------------- 将[传入的]device.data赋值给[传入的]device.oData
    let data = xj.attrIdDataToNamedata(device.oData); // -------------------------------------------------------- 根据protocol设备协议，将[传入的]device.data的键名转化为name
    let needReport = !xj.equalMap(xj.device.data, data);
    device.data = data;
    xj.combindMap(xj.device, device); // --------------------------------------------------------------------------- 将转化键名后的[传入的]device合并到[xj的]device
    xj.page.onDeviceInfoChange && xj.page.onDeviceInfoChange(xj.device.info); // ----------------------------------- 执行页面page中的onDeviceInfoChange、onDeviceDataChange 刷新device的info、data
    if (needReport) {
      xj.page.onDeviceDataChange && xj.page.onDeviceDataChange(xj.device.data);
    }
  },

  /* 上报设备变化的封装，原生需要调用这个方法上报设备变化，触发 onDeviceInfoChange */
  onDeviceInfoChange: function (info) {
    // ------------------------------------------------------------------------ [这是给设备调用的，注意和page的刷新区分]
    if (xj.equalMap(xj.device.info, info)) {
      // ------------------------------------------------------------------- 若传入info和xj.device.info不同，赋值新的info，执行页面中的onDeviceInfoChange刷新info
      return;
    }
    xj.device.info = info;
    xj.page.onDeviceInfoChange && xj.page.onDeviceInfoChange(xj.device.info);
  },

  onDeviceDataChange: function (data) {
    // ------------------------------------------------------------------------ [这是给设备调用的，注意和page的刷新区分] 将新传入的data，根据protocol转化，再启动页面刷新data
    xj.combindMap(xj.device.oData, data); // ----------------------------------------------------------------------- 合并传入的data到xj.device.data
    data = xj.attrIdDataToNamedata(xj.device.oData); // ------------------------------------------------------------ 根据protocol设备协议，将xj.device.oData键名转化为name，再赋值给data
    if (xj.equalMap(xj.device.data, data)) {
      // ------------------------------------------------------------------- 将转化后的data覆盖到xj.device.data
      return;
    }
    xj.device.data = data;
    xj.page.onDeviceDataChange && xj.page.onDeviceDataChange(xj.device.data); // ----------------------------------- 执行页面中的onDeviceDataChange刷新data
  },

  onGetStatusBarHeight: function (data) {},
  onDeviceOnline: function (data) {},

  /* 设备协议 */
  protocol: {},

  /**
   *
   * @param {attrId: {name, typeId}} protocol
   */

  importProtocol: function (protocol) {
    // ------------------------------------------------------------------------ 传参导入protocol设备协议(不传默认为{}),可以自动完成蓝牙设备数据的 name 和 attrId 转换，下发和上报只需要关心属性名称即可
    if (!protocol) {
      protocol = {};
    }
    xj.protocol = protocol;
    if (xj.device.oData) {
      xj.device.data = xj.attrIdDataToNamedata(xj.device.oData);
    }
    console.log("~~~~~~~~~~~~~~~~~~~~~xj.protocol=", xj.protocol);
  },

  addProtocol: function (protocol) {
    // --------------------------------------------------------------------------- 检测新传入的protocol，和xj.protocol不同，则合并到xj.protocol中
    if (protocol && !xj.protocol) {
      xj.protocol = protocol;
    } else {
      xj.combindMap(xj.protocol, protocol);
      xj.protocol = { ...xj.protocol };
    }
    if (xj.device.oData) {
      xj.device.data = xj.attrIdDataToNamedata(xj.device.oData); // ------------------------------------------------ 然后根据新的protocol，再对data做一次键名转化
    }
  },

  __protocolNameToId: function (name) {
    // ------------------------------------------------------------------------ 传params的key值，根据protocol设备协议，返回对应的attrId
    for (const attrId in xj.protocol) {
      if (Object.hasOwnProperty.call(xj.protocol, attrId)) {
        const protocol = xj.protocol[attrId];
        if (protocol.name === name) {
          return attrId;
        }
      }
    }
    return null;
  },

  attrIdDataToNamedata: function (attrIdData) {
    // ---------------------------------------------------------------- 传入的data，根据protocol设备协议，将键名转化为name，例如'0x01'转化为'powerstate'
    attrIdData = { ...attrIdData };
    if (!xj.protocol) {
      return attrIdData;
    }
    for (const attrId in attrIdData) {
      if (Object.hasOwnProperty.call(attrIdData, attrId)) {
        const value = attrIdData[attrId];
        const protocol = xj.protocol[attrId];
        if (protocol) {
          delete attrIdData[attrId];
          attrIdData[protocol.name] = value;
        }
      }
    }
    return attrIdData;
  },

  /* 本地配置 */
  config: {
    // ---------------------------------------------------------------------------------------------------- 本地存储相关操作
    get: function (params) {
      xj.handleCallBackParams(params, "result");
      xj.msgToNative("configGet", params);
    },
    set: function (params) {
      xj.handleCallBackParams(params, "result");
      xj.msgToNative("configSet", params);
    },
    merge: function (params) {
      xj.handleCallBackParams(params, "result");
      xj.msgToNative("configMerge", params);
    },
    delete: function (params) {
      xj.handleCallBackParams(params, "result");
      xj.msgToNative("configDelete", params);
    }
  },

  /* 初始化多语言信息，原生需要在 onLoad 前调用完成赋值 */
  stringsInit: function (code, strings) {
    // ---------------------------------------------------------------------- 初始化赋值 xj.languageCode、xj.strings
    xj.languageCode = code;
    xj.strings = strings;
  },

  getString: function (key) {
    // ---------------------------------------------------------------------------------- 返回对应字段（多语言的解决方案？）
    return xj.strings[key];
  },

  setNavigationBarButton: function (params) {
    // ------------------------------------------------------------------ 各种简单处理，转发ios、android操作
    let i = 0;
    for (var value of params) {
      xj.handleCallBackParams(value, "action", "navigationBarAction_" + i);
      i++;
    }
    xj.msgToNative("setNavigationBarButton", params);
  },
  showAlert: function (dic) {
    xj.handleCallBackParams(dic, "result");
    xj.msgToNative("showAlert", dic);
  },
  showPicker: function (dic) {
    xj.handleCallBackParams(dic, "result");
    xj.msgToNative("showPicker", dic);
  },
  setNavigationBarTitle: function (title) {
    xj.msgToNative("setNavigationBarTitle", title);
  },
  openSettingsPage: function (params) {
    xj.msgToNative("openSettingsPage", params);
  },
  showToast: function (dic) {
    xj.msgToNative("showToast", dic);
  },
  hideToast: function (dic) {
    xj.msgToNative("hideToast", dic);
  },
  hidePicker: function (dic) {
    xj.msgToNative("hidePicker", dic);
  },
  navigationTo: function (path, params) {
    var msg = params ? [path, params] : path;
    xj.msgToNative("navigationTo", msg);
  },
  getStatusBarHeight: function () {
    xj.msgToNative("getStatusBarHeight");
  },
  getDeviceOnline: function () {
    xj.msgToNative("getDeviceOnline");
  },
  showNavigationBar: function () {
    xj.msgToNative("showNavigationBar");
  },
  hideNavigationBar: function () {
    xj.msgToNative("hideNavigationBar");
  }
};

const xj = xj_that.xj;

xj.page = {
  // ---------------------------------------------------------------------------------------------------- 默认声明page的对象，内部各种初始化的方法（正常执行后，会被页面传入的page代替）
  onLoad: function (options) {},
  onReady: function () {},
  onShow: function () {},
  onHide: function () {},
  onUnload: function () {},
  onGetDarkMode: function (isDarkMode) {},
  onBleStateChange: function (bleState) {},
  onBleConnectStateChange: function (connectState) {},
  onDeviceInfoChange: function (info) {},
  onDeviceDataChange: function (data) {}
};

export { xj, removeMessageEvent };
