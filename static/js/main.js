(function(){
  const input = document.getElementById('wordInput');
  const sendBtn = document.getElementById('sendBtn');
  const errorBox = document.getElementById('error');
  const historyEl = document.getElementById('history');
  const expectInfo = document.getElementById('expectInfo');

  function appendHistory(player, word){
    const li = document.createElement('li');
    li.className = player === 'you' ? 'you' : 'ai';
    const chip = document.createElement('span');
    chip.className = 'chip ' + (player === 'you' ? 'me' : 'ai');
    chip.textContent = player === 'you' ? 'あなた' : 'AI';
    const w = document.createElement('span');
    w.className = 'word';
    w.textContent = word;
    li.appendChild(chip);
    li.appendChild(w);
    historyEl.appendChild(li);
  }

  function setError(msg){
    errorBox.textContent = msg || '';
  }

  function setExpect(ch){
    if (!ch){ expectInfo.textContent = ''; return; }
    expectInfo.textContent = '次は「' + ch + '」で始まることば';
  }

  async function send(){
    setError('');
    const word = (input.value || '').trim();
    if (!word) { setError('ことばを入力してください'); return; }

    try {
      const form = new FormData();
      form.append('word', word);
      const res = await fetch('/play', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok || !data.ok){
        setError(data.error || 'エラーが発生しました');
        return;
      }
      appendHistory('you', word);

      if (data.ai){
        appendHistory('ai', data.ai);
        setExpect(data.next_head || '');
      } else {
        setExpect('');
      }
      input.value = '';
    } catch(e){
      setError('接続に失敗しました');
    }
  }

  sendBtn?.addEventListener('click', function(e){ e.preventDefault(); send(); });
  input?.addEventListener('keydown', function(e){ if(e.key === 'Enter'){ e.preventDefault(); send(); } });

  // Initialize expected char from last history
  (function init(){
    const items = historyEl.querySelectorAll('li .word');
    if (items.length){
      const last = items[items.length - 1].textContent;
      const ch = last.slice(-1);
      setExpect(ch);
    }
  })();
})();
