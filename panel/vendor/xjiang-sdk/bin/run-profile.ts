import { existsSync, promises as fs } from "node:fs";
/// @1ts-nocheck
import { dirname } from "node:path";
import { parse } from "node:url";
import { Plugin } from "vite";

interface Options {
  url: string;
  /**
   * configFilejson文件生成的路径
   */
  configFile?: string;
}

export default async (options: Options): Promise<Plugin> => {
  const opt: Options = Object.assign(
    options
  );

  if (!opt.url || opt.url.length === 0) {
    throw new Error(`【vite-plugin-profile options url parameter is required`);
  }
  const JS_URL = opt?.url;
  const JS_CONTENTS: any = await readFileToString(JS_URL);
  
  return {
    name: "vite-plugin-profile",
    async configResolved() {
      try {
        // 导出文件已存在就不再更新
        const DEVICE_JSON = await existsSync(opt?.configFile);

        if (opt.configFile && !DEVICE_JSON) {
          const newProfileJson = createConfig(JS_CONTENTS);
          const newProfileJsonString = JSON.stringify(newProfileJson);
          generateFile(opt.configFile, newProfileJsonString);
        }
      } catch(e) {
        console.log("create device file error!");
      }
    },
    // generateBundle: () => {},
  };
};

/***
 * 获取本地文件内容，字符串内容输出
 */
async function readFileToString(filePath): Promise<string> {
  return new Promise(async (resolve, reject) => {
    try {
      const fileContent = await fs.readFile(filePath);
      resolve(JSON.parse(fileContent.toString()));
    } catch (error) {
      console.log(`读取文件失败：${error}`);
      reject(error);
    }
  });
}

/**
 * 生成文件
 * @param path
 * @param content
 */
async function generateFile(filepath, content) {
  const originalContent = existsSync(filepath) ? await fs.readFile(filepath, "utf-8") : "";
  originalContent !== content && writeFile(filepath, content);
}

/**
 * 写文件
 * @param filePath
 * @param content
 * @returns
 */
async function writeFile(filePath: string, content = "") {
  await fs.mkdir(dirname(filePath), { recursive: true });
  return await fs.writeFile(filePath, content, "utf-8");
}

type ProfileJsonType = {
  product: object;
  services: Object;
};
type ConfigJsonType = {
  type: string,
  info: object,
  data: object
};
/**
 * 转化profile格式
 */
function createConfig(profileJson) {
  let newConfigJson = {
    type: "",
    basicConfig: {
      defaultData: true // 设置默认初始值
    },
    info: {},
    data: {}
  };
  const _PRODUCT = profileJson?.product,
    _SERVICES = profileJson?.services;
  if (_PRODUCT) {
    newConfigJson = {
      ...newConfigJson,
      type: _PRODUCT?.netTypeId === 3 ? 'mesh' : _PRODUCT?.netTypeId === 2 ? 'ble' : 'wifi',
      info: { 
        ...newConfigJson?.info,
        displayName: _PRODUCT?.productName
      }
    }
  }
  if (_SERVICES) {
    _SERVICES.forEach(service => {
      const _serviceName = service?.serviceName || service?.siid,
        _properties = service?.properties;
      if (_properties && _properties.length) {
        _properties.forEach(prop => {
          if (service?.siid && prop.piid) {
            const _propKey = prop?.description || prop.piid;
            const _v = prop?.format === "string" ? "" : prop?.format === "bool" ? false : 
              prop?.format === "int" ? handleInt(prop) : null;

            const newK = (`${ _serviceName }_${ _propKey }`).replace(/-/g, "_");
            newConfigJson = { 
              ...newConfigJson, 
              data: {
                ...newConfigJson?.data,
                [`${ newK }`]: 
                  { 
                    key: `prop.${ service?.siid }.${ prop?.piid }`,
                    value: _v
                  } 
              }
            };
          }
        })
      }
    });
  }
  return newConfigJson;
}

type ConfigPropsType = { 
  value: number, 
  valueList?: Array<{ description: string, value: number | string }>, 
  valueRange?: number[] 
};
function handleInt(params: ConfigPropsType) {
  const { value, valueList, valueRange } = params;
  if (!isNaN(Number(value))) return 0;

  let _v = 0;
  if (valueList && valueList.length) {
    _v = Number(valueList[0]?.value)
  } else if (valueRange && valueRange.length) {
    _v = Number(valueRange[0])
  }
  return _v;
}
