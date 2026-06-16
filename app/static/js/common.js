function showToast(message, type='success') {
  const stack = document.getElementById('toastStack') || (() => {
    const s = document.createElement('div'); s.id='toastStack'; s.className='toast-stack'; document.body.appendChild(s); return s;
  })();
  const t = document.createElement('div'); t.className='toast '+type; t.textContent=message;
  stack.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function humanSize(bytes){
  if(!bytes) return '0 B';
  const units=['B','KB','MB','GB'];
  let i=0, size=bytes;
  while(size>=1024 && i<units.length-1){ size/=1024; i++; }
  return size.toFixed(1)+' '+units[i];
}

// Error reporter: only on authenticated pages (skip login page)
(function initErrorReporter(){
  const path = location.pathname;
  if(path === '/login' || path.startsWith('/static/')) return;
  if(!window.__errorReporterInstalled){
    window.__errorReporterInstalled = true;
    window.addEventListener('error', function(e){
      reportJsError(e.message || 'Uncaught error', e.error && e.error.stack ? e.error.stack : e.filename + ':' + e.lineno, 'error');
    });
    window.addEventListener('unhandledrejection', function(e){
      let msg = 'Unhandled promise rejection';
      let stack = '';
      if(e.reason){
        msg = e.reason.message || String(e.reason);
        stack = e.reason.stack || String(e.reason);
      }
      reportJsError(msg, stack, 'error');
    });
  }
})();

function reportJsError(message, stack, level){
  try{
    const payload = {
      message: String(message).slice(0,1000),
      stack: String(stack || '').slice(0,4000),
      url: location.href,
      level: level || 'error'
    };
    navigator.sendBeacon('/api/error-log', new Blob([JSON.stringify(payload)], {type:'application/json'}));
  }catch(e){ /* silent */ }
}
