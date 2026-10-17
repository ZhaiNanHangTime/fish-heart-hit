/* Shared snapshot channel. Configuration is broadcast with the same snapshot. */
window.HRLive = (() => {
  let latest = null, received = 0;
  const listeners = new Set();
  let es = null;
  const emit = snap => listeners.forEach(fn => fn(snap));
  function connect() {
    if (es) return;
    es = new EventSource('/events');
    es.onmessage = event => {
      try { latest = JSON.parse(event.data); }
      catch (error) { console.error('心率快照解析失败', error); return; }
      received = performance.now();
      emit({...latest,stream_online:true});
    };
    es.onerror = () => { if (latest) emit({...latest, bpm:null, connected:false,stream_online:false}); };
  }
  addEventListener('pagehide', () => { if (es) es.close(); es = null; });
  addEventListener('pageshow', () => { if (listeners.size) connect(); });
  setInterval(() => {
    if (latest && performance.now() - received > 5000)
      emit({...latest, bpm:null, connected:false,stream_online:false});
  }, 1000);
  return {subscribe(fn) {
    listeners.add(fn);
    connect();
    if (latest) fn(latest);
    return () => {
      listeners.delete(fn);
      if (!listeners.size && es) { es.close(); es = null; }
    };
  }};
})();
