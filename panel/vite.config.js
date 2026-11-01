import { defineConfig } from 'vite';
import {fileURLToPath} from 'node:url';
export default defineConfig({base: './',
  resolve: {alias: [{find: '../../../xjiang-ui', replacement: fileURLToPath(new URL('./src/sdk-ui.js',import.meta.url))}]},
  build: {target: 'es2020', rolldownOptions: {input: {
    device: fileURLToPath(new URL('./index.html', import.meta.url)),
    setup: fileURLToPath(new URL('./setup.html', import.meta.url))
  }}}, server: {host: '127.0.0.1'}
});
