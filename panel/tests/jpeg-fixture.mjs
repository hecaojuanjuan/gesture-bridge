// Synthetic 2×1 JPEG; no camera/user image is included in this fixture.
export const jpegBase64='/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAABAAIDAREAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDovBn/ACJ+hf8AXhB/6LWv4tx3+91f8UvzZ/GHij/yXuf/APYZif8A09M//9k=';
export const jpegBytes=Uint8Array.from(atob(jpegBase64),character=>character.charCodeAt(0));
export function jpegWire({wait=true,width=2,height=1,captured=12345,data=jpegBytes,source='model'}={}) {
  let hash=2166136261;
  for(const byte of data) hash=Math.imul(hash^byte,16777619)>>>0;
  const lines=[];
  if(wait) lines.push('HVJPEG WAIT');
  lines.push(`HVJPEG SOURCE ${source}`,`HVJPEG BEGIN 1 ${width} ${height} ${data.length} ${captured} 0 75`);
  for(let offset=0;offset<data.length;offset+=192)
    lines.push(`HVJPEG DATA ${offset} ${btoa(String.fromCharCode(...data.slice(offset,offset+192)))}`);
  lines.push('HVJPEG END '+hash.toString(16).padStart(8,'0'));
  return lines.join('\n')+'\n';
}
export function decodedFrame(encoded) {
  return {width:encoded.width,height:encoded.height,capturedMs:encoded.capturedMs,
    rgba:new Uint8ClampedArray(encoded.width*encoded.height*4),encoding:'jpeg'};
}
