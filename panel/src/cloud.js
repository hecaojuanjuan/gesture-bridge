import XJIotSDK from 'xjiang-sdk';
import mapping from '../protocol.json';
export function connectCloud(onReport, onLost, onReady) {
  const host = window.ReactNativeWebView?.postMessage ||
    ((window.__wxjs_environment === 'miniprogram' || /MicroMessenger/i.test(navigator.userAgent)) &&
      new URLSearchParams(location.search).has('token'));
  if (!host) throw Error('请从灵机小程序或 App 的设备页打开云端面板；本地可使用 USB 串口。');
  const sdk = new XJIotSDK({type: 'wifi', basicConfig: {defaultData: false},
    info: {displayName: '颔语'}, data: {
      panel_command: {key: `prop.${mapping.siid}.${mapping.commandPiid}`, value: ''},
      panel_report: {key: `prop.${mapping.siid}.${mapping.reportPiid}`, value: ''}
    }});
  sdk.initProject({
    onDeviceDataChange: data => { if (typeof data?.panel_report === 'string') onReport(data.panel_report); },
    onPageConnectChange: connected => { if (connected === false) onLost('灵机连接中断，请重新连接'); },
    onPageInit: () => onReady()
  });
  sdk.pageInit({key: 'headvoice-panel', onLoad: () => { sdk.device.get([]); onReady(); }});
  return {name: '灵机云端',
    async send(wire) { await sdk.device.set({panel_command: wire}); },
    async close() { sdk.exit(); }
  };
}
