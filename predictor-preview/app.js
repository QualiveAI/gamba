/* Локальная deterministic anti-pattern simulation. Нет сети, Telegram, DB, wallet или live outcomes. */
(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const hashSeed = (seed) => [...String(seed)].reduce((hash, char) => ((hash * 31) + char.charCodeAt(0)) >>> 0, 2166136261);
  const rng = (seed) => {
    let state = hashSeed(seed) || 1;
    return () => { state = (1664525 * state + 1013904223) >>> 0; return state / 4294967296; };
  };
  const stakeBuckets = [
    { id: 'low', label: 'Низкая', amount: '< 100', biasedAccuracy: 0.86 },
    { id: 'medium', label: 'Средняя', amount: '100–499', biasedAccuracy: 0.58 },
    { id: 'high', label: 'Высокая', amount: '500+', biasedAccuracy: 0.23 },
  ];

  function nextTruth(game, random) {
    if (game === 'mines') return random() > 0.24;
    if (game === 'cups') return random() > 0.66;
    const roll = random();
    return (0.97 / Math.max(0.000001, 1 - roll)) >= 2;
  }

  function simulate({ game, mode, rounds, seed }) {
    const random = rng(`${seed}:${game}:${mode}`);
    const stats = stakeBuckets.map(bucket => ({ ...bucket, correct: 0, wrong: 0, losses: 0 }));
    for (let i = 0; i < rounds; i += 1) {
      for (const bucket of stats) {
        const truth = nextTruth(game, random);
        const accuracy = mode === 'biased' ? bucket.biasedAccuracy : 0.58;
        const signal = random() < accuracy ? truth : !truth;
        if (signal === truth) stats.find(row => row.id === bucket.id).correct += 1;
        else {
          const row = stats.find(item => item.id === bucket.id);
          row.wrong += 1;
          if (signal === false && truth === true) row.losses += 1;
        }
      }
    }
    return stats.map(row => ({ ...row, accuracy: row.correct / rounds, error: row.wrong / rounds, losses: row.losses }));
  }

  function renderChart(stats) {
    const width = 800, height = 220, left = 55, bottom = 32, plotW = 700, plotH = 155;
    const x = index => left + (plotW / (stats.length - 1)) * index;
    const y = value => 18 + plotH * (1 - value);
    const lines = (key, className) => `<polyline class="chart-line ${className}" fill="none" stroke-width="4" points="${stats.map((row, i) => `${x(i)},${y(row[key])}`).join(' ')}"/>`;
    const dots = key => stats.map((row, i) => `<circle class="chart-dot" cx="${x(i)}" cy="${y(row[key])}" r="6"><title>${row.label}: ${(row[key] * 100).toFixed(1)}%</title></circle>`).join('');
    return `<line class="chart-grid" x1="${left}" y1="${y(.5)}" x2="${left + plotW}" y2="${y(.5)}"/><line class="chart-grid" x1="${left}" y1="${y(1)}" x2="${left + plotW}" y2="${y(1)}"/>${lines('accuracy','low')}${dots('accuracy')}${stats.map((row, i) => `<text x="${x(i)}" y="${height - 8}" fill="#a8adba" text-anchor="middle">${row.label}</text>`).join('')}<text x="10" y="22" fill="#a8adba">100%</text><text x="10" y="${y(.5) + 4}" fill="#a8adba">50%</text>`;
  }

  function render(stats, mode, game) {
    const total = stats.reduce((sum, row) => sum + row.correct + row.wrong, 0);
    const accuracy = stats.reduce((sum, row) => sum + row.correct, 0) / total;
    const losses = stats.reduce((sum, row) => sum + row.losses, 0);
    $('#mode-pill').textContent = mode === 'biased' ? 'ANTI-PATTERN' : 'BASELINE';
    $('#mode-pill').classList.toggle('fair', mode !== 'biased');
    $('#result-title').textContent = `${game === 'mines' ? 'Minas' : game === 'crash' ? 'Crash / Foguete' : 'Copos'} · ${mode === 'biased' ? 'манипулируемый сигнал' : 'нейтральный baseline'}`;
    $('#metrics').innerHTML = `<div class="metric"><b>${(accuracy * 100).toFixed(1)}%</b><small>среднее качество</small></div><div class="metric"><b>${losses}</b><small>потенциально вредных советов</small></div><div class="metric"><b>${stats[0].accuracy * 100 | 0}%</b><small>низкая ставка</small></div><div class="metric"><b>${stats[2].accuracy * 100 | 0}%</b><small>высокая ставка</small></div>`;
    $('#chart').innerHTML = renderChart(stats);
    $('#rows').innerHTML = stats.map(row => `<tr><td>${row.label}<br><small>${row.amount}</small></td><td>${(row.accuracy * 100).toFixed(1)}%</td><td>${(row.error * 100).toFixed(1)}%</td><td>${row.losses}</td></tr>`).join('');
    $('#result-note').textContent = mode === 'biased'
      ? 'Видно, как ставка меняет качество сигнала. Это намеренная манипуляция для демонстрации и не должна подключаться к WINDROP.'
      : 'Baseline не получает размер ставки и не обещает следующий результат. Это статистическая иллюстрация, а не прогноз.';
  }

  function run() {
    const rounds = clamp(Number($('#rounds').value) || 500, 10, 10000);
    const game = $('#game').value;
    const mode = $('#mode').value;
    const seed = $('#seed').value || 'preview';
    render(simulate({ game, mode, rounds, seed }), mode, game);
  }
  $('#run').addEventListener('click', run);
  run();
  globalThis.WindropPredictorPreview = Object.freeze({ simulate, stakeBuckets });
})();
