export function icon(name, size=22) {
  const paths={
    plus:'<path d="M12 5v14M5 12h14"/>', book:'<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4zM13 7a3 3 0 0 1 3-3h4v14h-3a4 4 0 0 0-4 3"/>',
    grid:'<rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><rect x="14" y="14" width="6" height="6" rx="1.5"/>',
    check:'<path d="m5 12 4 4L19 6"/>', arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>', back:'<path d="M19 12H5m6-6-6 6 6 6"/>',
    sound:'<path d="M11 4 6 8H3v8h3l5 4zM15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
    monitor:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
    help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 8.5a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 16h.01"/>',
    person:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    edit:'<path d="m14 5 5 5M4 20l5-1L20 8a2 2 0 0 0-5-5L4 14z"/>',
    trash:'<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v6m4-6v6"/>',
    pause:'<path d="M8 5v14M16 5v14"/>', play:'<path d="m8 4 12 8-12 8z"/>',
    reset:'<path d="M3 4v6h6M3 10a9 9 0 1 1 2 9"/>', shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
    link:'<path d="m10 13 4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2-2 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" transform="translate(1 1) scale(.9)"/>',
    close:'<path d="m6 6 12 12M6 18 18 6"/>',
  };
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.help}</svg>`;
}
// Purpose-built vector illustrations, intentionally distinct from camera images.
export function illustration(name) {
  const art={
    water:'<ellipse cx="80" cy="111" rx="43" ry="7" fill="#d5e6e8"/><path d="M49 28h60l-6 73q-23 12-48 0z" fill="#fff" stroke="#497b87" stroke-width="3"/><path d="M53 65q12-7 24 0t26 0l-3 33q-21 10-42 0z" fill="#80bac9"/><path d="M63 39v15M61 75l2 17" stroke="white" stroke-width="4" stroke-linecap="round"/><path d="M121 27c0 6 9 6 9 0 0-4-4-9-4-9s-5 5-5 9" fill="#97c4d0"/>',
    rest:'<ellipse cx="80" cy="113" rx="53" ry="6" fill="#ddd8e9"/><path d="M30 75h100v30H30z" fill="#b5a3cd" stroke="#75638c" stroke-width="3"/><path d="M30 56v56m100-44v44M32 68h42v19H32" fill="#fff" stroke="#75638c" stroke-width="3" stroke-linejoin="round"/><path d="M74 66h42q14 0 14 14v8H74z" fill="#e1d9ef" stroke="#75638c" stroke-width="3"/><path d="M103 21a17 17 0 1 0 22 22 17 17 0 0 1-22-22" fill="#b4a0cf"/><path d="m70 32 3 5 6 1-5 4 1 6-5-3-5 3 1-6-5-4 6-1z" fill="#ccb9e1"/>',
    help:'<ellipse cx="80" cy="112" rx="46" ry="6" fill="#ead6cb"/><path d="M35 83 61 68q7-4 12 2l13 11 15-13q6-5 11 0l15 17-29 24H64z" fill="#dca68b"/><path d="m28 86 18 25 15-10-18-26z" fill="#608b7c"/><path d="m130 88-18 23-14-12 17-25z" fill="#f5f2e7" stroke="#ab806b" stroke-width="2"/><path d="m62 77 15 12q5 4 9-1l9-9M72 97l9 7m0-15 12 11" fill="none" stroke="#9c6d57" stroke-width="2.5" stroke-linecap="round"/><path d="M80 54S59 42 59 31c0-13 17-15 21-4 5-11 21-9 21 4 0 11-21 23-21 23" fill="#ca8168"/>',
    toilet:'<ellipse cx="80" cy="114" rx="42" ry="6" fill="#e6dfca"/><rect x="44" y="28" width="51" height="43" rx="6" fill="#faf9f1" stroke="#8e896c" stroke-width="3"/><path d="M46 72h74q0 28-30 28l4 12H66l5-19q-25-7-25-21" fill="#efecdd" stroke="#8e896c" stroke-width="3"/><rect x="41" y="66" width="81" height="9" rx="4.5" fill="#c7c3a4" stroke="#8e896c" stroke-width="2"/><path d="M77 40h8" stroke="#8e896c" stroke-width="4" stroke-linecap="round"/>',
    cold:'<ellipse cx="80" cy="113" rx="46" ry="6" fill="#d3e3d7"/><path d="m62 31-25 14-14 29 20 10 9-17v42h56V67l9 17 20-10-14-29-25-14q-18 17-36 0" fill="#91b8a0" stroke="#4e7c65" stroke-width="3" stroke-linejoin="round"/><path d="M64 31q16 26 32 0M59 96h42M80 47v48" fill="none" stroke="#4e7c65" stroke-width="3"/><path d="m28 22 6 6m-6 0 6-6m98-3v12m-5-9 10 6m-10 0 10-6" stroke="#8ab69c" stroke-width="2.5" stroke-linecap="round"/>',
    company:'<ellipse cx="80" cy="113" rx="52" ry="6" fill="#e8d7da"/><circle cx="55" cy="48" r="16" fill="#d8a98e"/><circle cx="105" cy="48" r="16" fill="#e1b69d"/><path d="M39 43q0-20 17-20 17 0 17 22l-12-10-21 10" fill="#7e8078"/><path d="M89 42q0-19 17-19 17 0 17 22l-13-9-20 9" fill="#a09693"/><path d="M29 108V86q0-23 26-23t26 23v22" fill="#769b91"/><path d="M80 108V86q0-23 25-23t26 23v22" fill="#c9969d"/><path d="m64 82 16 14 17-14" fill="none" stroke="#f6eee8" stroke-width="7" stroke-linecap="round"/><path d="M78 33s-10-6-10-11 8-7 10-2c3-5 11-4 11 2s-11 11-11 11" fill="#ca8c98"/>',
    palm:'<path d="M57 111 40 78q-6-12 2-15 7-3 14 11V37q0-12 10-12 8 0 8 12v22-41q0-11 9-11t9 11v40-34q0-11 9-11t9 11v39-26q0-11 9-11t9 11v45q0 31-18 39z" fill="#e6c3a7" stroke="#9f785f" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="M75 79q19-13 35 0M83 88v13" fill="none" stroke="#c69a7b" stroke-width="2.5" stroke-linecap="round"/>',
    victory:'<path d="m62 68-9-46q-3-12 6-14t12 10l12 40 16-41q4-10 12-6t4 15L99 72q15-8 22 2l-2 27q-2 18-20 21H72q-18-2-22-19l-6-22q-2-13 8-13 7 0 10 10z" fill="#e6c3a7" stroke="#9f785f" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="M64 70q7-10 16-3l12 13q5 8-2 13-6 4-12-4l-13-12M96 68l12 12q5 8-3 12" fill="none" stroke="#9f785f" stroke-width="3" stroke-linecap="round"/>',
  };
  return `<svg viewBox="0 0 160 132" fill="none" aria-hidden="true">${art[name]||art.help}</svg>`;
}
