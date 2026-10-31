/**
 * 对单个数据改变做防抖
 */
export function debonuceDataChanged<T>() {
  let cache = {} as Partial<T>,
    timer: any;
  return (data: Partial<T>, callback: (data: Partial<T>) => void) => {
    timer && clearTimeout(timer);
    for (const key in data) {
      cache[key] = data[key];
    }
    timer = setTimeout(() => {
      callback(cache);
      cache = {};
      timer = null;
    }, 50);
  };
}

/**
 * 代理处理器
 * @param callback 回调函数
 */
export function proxyHandler<T extends object>(
  callback: (arg: Partial<T>) => void
): ProxyHandler<T> {
  const fn = debonuceDataChanged();
  return {
    set(target, key, value) {
      const oldValue = target[key as keyof T];
      if (oldValue === value) {
        return true;
      }
      target[key as keyof T] = value;
      fn({ [key]: value }, callback);
      return true;
    },
  };
}

  /***
   * 获取url参数
   */
  export function getUrlQueryString(name: string){
    const url = decodeURI(location.href); //获取url中"?"符后的字串
    let theRequest: any = {};
    if (url.indexOf("?") !== -1) {
      try {
        const str = url.split("?")[1];
        const strs = str.split("&");
        for (let i = 0; i < strs.length; i++) {
          const _v = unescape(strs[i].split("=")[1]).replace(/[#/]/g, '');  
          theRequest = { ...theRequest, [`${strs[i].split("=")[0]}`]: _v }
        }
      } catch(e) {
        return null
      }
    }
    return Object.keys(theRequest).includes(name) ? theRequest[name] : null;
  }
  
  export const pxToRem = (value: number) => `${Number(value)}px`;