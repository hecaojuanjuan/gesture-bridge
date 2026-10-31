import { defineConfig } from 'vite';
import {fileURLToPath} from 'node:url';
export default defineConfig({base: './',
  resolve: {alias: [{find: '../../../xjiang-ui', replacement: fileURLToPath(new URL('./src/sdk-ui.js',import.meta.url))}]},
  build: {target: 'es2020'}, server: {host: '127.0.0.1'}
});
