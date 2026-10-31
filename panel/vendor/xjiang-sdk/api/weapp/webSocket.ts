type wsType = {
	url: string;
	protocol: any;
	onOpen?: ((ws: WS, ev: Event) => any) | null;
	onMessage?: ((ws: WS, ev: MessageEvent) => any) | null;
	onError?: ((ws: WS, ev: Event) => any) | null;
	onClose?: ((ws: WS, ev: CloseEvent) => any) | null;
}
class WS {
	url: string;
	ws: WebSocket;
	closure: Function;
	send: Function;
	constructor(params: wsType) {
		this.url = params.url;
		this.ws = new WebSocket("wss://" + this.url);
		this.closure = (): void => {
			this.ws.close();
		};
		this.send = (msg: any): void => {
			if (typeof msg !== "string")
				msg = JSON.stringify(msg)
			console.log("==send data====>", msg)
			this.ws.send(msg);
		};
		
		this.ws.onopen = (ev: Event): any => {
			if(!!params?.onOpen) {
				params.onOpen(this, ev);
			}
			console.log(`websocket${this.url}连接开启！`);
		};
		
		this.ws.onmessage = (ev: MessageEvent): any => {
			if(!!params?.onMessage) {
				params.onMessage(this, ev);
			}
			console.log(`websocket${this.url}收到信息：${JSON.stringify(ev)}！`);
		};
		
		this.ws.onerror = (ev: Event): any => {
			if(!!params?.onError) {
				params?.onError(this, ev);
			}
			console.log(`websocket${this.url}连接error：${JSON.stringify(ev)}！`);
		};
		
		this.ws.onclose = (ev: CloseEvent): any => {
			if(!!params?.onClose) {
				params?.onClose(this, ev);
			}
			console.log(`websocket${this.url}连接关闭！`);
		};
	}
}
 
export default WS;