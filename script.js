// script.js - Fixed version with correct display and calculation
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const THEME_KEY = "procalc:theme";
const CONTRAST_KEY = "procalc:contrast";
const HISTORY_KEY = "procalc:history";
const MEMORY_KEY = "procalc:memory";

// Simple Expression Evaluator with proper BODMAS
function safeEvaluate(expression) {
  try {
    // Clean the expression
    let expr = expression.replace(/[^0-9+\-*/.()%]/g, '');

    // Handle percentage: convert X% to (X/100)
    expr = expr.replace(/(\d+(?:\.\d+)?)%/g, '($1/100)');

    // Prevent division by zero
    if (expr.includes('/0')) {
      throw new Error('Division by zero');
    }

    // Use Function constructor for safe evaluation
    const result = new Function('return ' + expr)();

    if (!isFinite(result)) {
      throw new Error('Invalid result');
    }

    return parseFloat(result.toFixed(12));
  } catch (e) {
    throw new Error('Invalid expression');
  }
}

function formatNumber(num) {
  if (Math.abs(num) > 1e12 || (Math.abs(num) < 1e-6 && num !== 0)) {
    return num.toExponential(6);
  }
  return num.toString();
}

// UI State
const expressionEl = $("#expression");
const resultEl = $("#result");
const historyEl = $("#history");
const historyList = $("#historyList");
const historySearch = $("#historySearch");
const app = $(".app");
const voiceToggle = $("#voiceToggle");
const voiceStatusEl = $("#voiceStatus");
const micCoach = document.getElementById('micCoach');

// Allow VOICE_API_BASE override via config.js, URL params, or localStorage
const params = new URLSearchParams(location.search);
const urlApi = params.get('api') || params.get('voice_api');
if (urlApi) {
  try {
    const u = new URL(urlApi);
    localStorage.setItem('PROCALC_VOICE_API_BASE', u.origin);
  } catch (e) {
    console.warn('Ignoring invalid api URL param:', urlApi);
  }
}
let VOICE_API_BASE = (window.PROCALC_VOICE_API_BASE || localStorage.getItem('PROCALC_VOICE_API_BASE') || "http://127.0.0.1:8000");

let currentExpression = "";
let memory = parseFloat(localStorage.getItem(MEMORY_KEY) || "0");
let history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
let shouldResetOnNextInput = false;

// Theme setup
const savedTheme = localStorage.getItem(THEME_KEY) || "dark";
if (app) app.dataset.theme = savedTheme;
const savedContrast = localStorage.getItem(CONTRAST_KEY) || "normal";
if (savedContrast === "high" && app) app.dataset.contrast = "high";

// Display functions
// ================ ENHANCED UPDATE DISPLAY (prevents animation conflicts) ================

function updateDisplay() {
  if (expressionEl) {
    expressionEl.textContent = currentExpression || "";
  }

  if (resultEl) {
    if (!currentExpression) {
      resultEl.textContent = "0";
      return;
    }

    try {
      // Only show preview if expression is not empty, doesn't end with operator, 
      // AND result element is not currently animating
      if (currentExpression &&
        !/[+\-*/%]$/.test(currentExpression) &&
        !resultEl.classList.contains('bounce-in') &&
        !resultEl.classList.contains('digit-cascade') &&
        !resultEl.classList.contains('typewriter') &&
        !resultEl.classList.contains('result-glow')) {

        const result = safeEvaluate(currentExpression);
        resultEl.textContent = formatNumber(result);
      } else if (!resultEl.classList.contains('bounce-in') &&
        !resultEl.classList.contains('digit-cascade') &&
        !resultEl.classList.contains('typewriter') &&
        !resultEl.classList.contains('result-glow')) {
        resultEl.textContent = "0";
      }
      // If result is animating, don't change its content
    } catch {
      if (!resultEl.classList.contains('bounce-in') &&
        !resultEl.classList.contains('digit-cascade') &&
        !resultEl.classList.contains('typewriter') &&
        !resultEl.classList.contains('result-glow')) {
        resultEl.textContent = "0";
      }
    }
  }
}


// ================ ENHANCED ERROR FUNCTION WITH ANIMATION ================

function showError(msg) {
  if (resultEl) {
    console.log(`❌ Showing error with animation: ${msg}`);

    // Add error shake animation to result
    resultEl.classList.remove('bounce-in', 'digit-cascade', 'typewriter', 'result-glow');
    resultEl.classList.add('error-shake');

    // Show error message
    resultEl.textContent = msg;
    resultEl.style.color = "var(--danger)";

    // Also add error effect to display background
    const displayEl = $('.display');
    displayEl.style.border = '2px solid var(--danger)';
    displayEl.style.boxShadow = '0 0 20px rgba(239, 68, 68, 0.3)';

    setTimeout(() => {
      resultEl.style.color = "";
      resultEl.classList.remove('error-shake');

      // Reset display styling
      displayEl.style.border = '';
      displayEl.style.boxShadow = '';

      updateDisplay();
      console.log('🧹 Cleaned up error animation');
    }, 2000);
  }
}


// ========================= VOICE CONTROL =========================
const voiceUI = {
  state: 'idle',
  message: 'Mic off',
  set(message, state = 'idle', level = 'info') {
    this.state = state;
    this.message = message;

    if (voiceStatusEl && level !== 'debug') {
      voiceStatusEl.textContent = message;
      voiceStatusEl.classList.toggle('state-listening', state === 'listening' || state === 'calibrating');
      voiceStatusEl.classList.toggle('state-error', state === 'error');
    }

    if (voiceToggle) {
      voiceToggle.classList.remove('mic-on', 'mic-error', 'mic-off');
      const pressed = state === 'listening' || state === 'calibrating';
      voiceToggle.setAttribute('aria-pressed', pressed ? 'true' : 'false');
      if (pressed) {
        voiceToggle.classList.add('mic-on');
      } else if (state === 'error') {
        voiceToggle.classList.add('mic-error');
      } else {
        voiceToggle.classList.add('mic-off');
      }
    }
  }
};

voiceUI.set('Mic off', 'idle');

let lastVoiceExpression = '';
let lastVoiceTimestamp = 0;

function deriveVoiceState(rawState) {
  if (['calibrating', 'listening'].includes(rawState)) return 'listening';
  if (rawState === 'error') return 'error';
  return 'idle';
}

function injectVoiceExpression(expression, confidence = 1) {
  if (!expression) return;
  const sanitized = expression.replace(/[^0-9+\-*/().]/g, '');
  if (!sanitized) return;

  const now = Date.now();
  if (sanitized === lastVoiceExpression && now - lastVoiceTimestamp < 300) {
    return;
  }

  if (shouldResetOnNextInput) {
    currentExpression = '';
    shouldResetOnNextInput = false;
  }

  currentExpression = sanitized;
  updateDisplay();

  if (expressionEl) {
    expressionEl.classList.add('voice-input');
    setTimeout(() => expressionEl.classList.remove('voice-input'), 600);
  }

  lastVoiceExpression = sanitized;
  lastVoiceTimestamp = now;

  if (confidence < 0.4) {
    voiceUI.set('Low confidence, please repeat', 'listening');
  }
}

function handleVoiceResult(payload) {
  switch (payload.action) {
    case 'append_expression':
      injectVoiceExpression(payload.expression, payload.expression_confidence ?? 1);
      break;
    case 'calculate':
      if (payload.expression) {
        injectVoiceExpression(payload.expression, payload.expression_confidence ?? 1);
      }
      calculate();
      break;
    case 'clear':
      if (payload.expression === null) {
        clearAll();
        break;
      }
      clearAll();
      break;
    case 'backspace':
      backspace();
      break;
    case 'stop':
      voiceControl.stop({ silent: false });
      break;
    default:
      break;
  }
}

function handleVoicePayload(payload) {
  if (!payload || typeof payload !== 'object') return;

  if (payload.type === 'status') {
    const state = deriveVoiceState(payload.state || 'idle');
    voiceUI.set(payload.message || 'Listening…', state, payload.level || 'info');
    return;
  }

  if (payload.type === 'result') {
    voiceUI.set('Listening…', 'listening');
    handleVoiceResult(payload);
  }
}

const voiceControl = {
  active: false,
  eventSource: null,
  reconnectTimer: null,
  reconnectAttempts: 0,
  async start() {
    if (this.active) {
      voiceUI.set('Listening…', 'listening');
      return;
    }

    voiceUI.set('Connecting to microphone…', 'calibrating');

    try {
      const response = await fetch(`${VOICE_API_BASE}/voice/start`, { method: 'POST' });
      if (!response.ok) {
        throw new Error(`Voice start failed: ${response.status}`);
      }

      this.active = true;
      this.reconnectAttempts = 0;
      this._openEventStream();
    } catch (error) {
      console.error('Voice service start error', error);
      this.active = false;
      voiceUI.set('Voice service unavailable', 'error');
    }
  },
  async stop({ silent } = { silent: false }) {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    try {
      await fetch(`${VOICE_API_BASE}/voice/stop`, { method: 'POST' });
    } catch (error) {
      console.warn('Voice service stop warning', error);
    }

    this.active = false;
    this.reconnectAttempts = 0;
    if (!silent) {
      voiceUI.set('Mic off', 'idle');
    }
  },
  toggle() {
    if (this.active) {
      this.stop();
    } else {
      this.start();
    }
  },
  _openEventStream() {
    if (this.eventSource) {
      this.eventSource.close();
    }

    this.eventSource = new EventSource(`${VOICE_API_BASE}/voice/stream`);

    this.eventSource.onmessage = (event) => {
      if (!event.data) return;
      try {
        const payload = JSON.parse(event.data);
        handleVoicePayload(payload);
      } catch (error) {
        console.error('Failed to parse voice payload', error);
      }
    };

    this.eventSource.addEventListener('ping', () => {
      if (this.active) {
        voiceUI.set('Listening…', 'listening');
      }
    });

    this.eventSource.onerror = () => {
      console.warn('Voice stream encountered an error');
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }

      if (!this.active) {
        voiceUI.set('Mic off', 'idle');
        return;
      }

      voiceUI.set('Reconnecting voice link…', 'error');
      this._scheduleReconnect();
    };
  },
  _scheduleReconnect() {
    if (this.reconnectTimer) {
      return;
    }

    if (this.reconnectAttempts >= 4) {
      console.error('Voice service reconnection exhausted');
      this.stop({ silent: true });
      voiceUI.set('Voice connection lost', 'error');
      return;
    }

    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(async () => {
      this.reconnectTimer = null;
      try {
        const response = await fetch(`${VOICE_API_BASE}/voice/start`, { method: 'POST' });
        if (!response.ok) throw new Error('Restart failed');
        this._openEventStream();
        voiceUI.set('Listening…', 'listening');
      } catch (error) {
        console.error('Voice reconnection failed', error);
        this._scheduleReconnect();
      }
    }, 2000);
  }
};

if (voiceToggle) {
  voiceToggle.addEventListener('click', () => voiceControl.toggle());
}

// API settings button: prompt for URL and persist
const apiSettingsBtn = document.getElementById('apiSettings');
if (apiSettingsBtn) {
  apiSettingsBtn.addEventListener('click', async () => {
    const current = VOICE_API_BASE || '';
    const input = prompt('Enter Voice API Base URL (e.g., https://abc.trycloudflare.com):', current);
    if (!input) return;
    try {
      const u = new URL(input);
      const newBase = u.origin;
      localStorage.setItem('PROCALC_VOICE_API_BASE', newBase);
      VOICE_API_BASE = newBase;
      // If connected, reconnect to the new base
      if (voiceControl.active) {
        await voiceControl.stop({ silent: true });
        await voiceControl.start();
      }
      alert(`Voice API set to: ${newBase}`);
    } catch (e) {
      alert('Invalid URL. Please enter a valid http(s) URL.');
    }
  });
}

window.addEventListener('beforeunload', () => {
  if (voiceControl.active) {
    voiceControl.stop({ silent: true });
  }
});

// ======================= END VOICE CONTROL =======================


// Input validation helpers
function isOperator(char) {
  return ['+', '-', '*', '/', '%'].includes(char);
}

function getLastChar() {
  return currentExpression.slice(-1);
}

function canAddOperator() {
  const lastChar = getLastChar();
  return currentExpression && !isOperator(lastChar) && lastChar !== '.';
}

function canAddDecimal() {
  const parts = currentExpression.split(/[+\-*/%]/);
  const lastPart = parts[parts.length - 1];
  return !lastPart.includes('.');
}

// Input handling
function addDigit(digit) {
  if (shouldResetOnNextInput) {
    currentExpression = "";
    shouldResetOnNextInput = false;
  }

  // Prevent multiple leading zeros
  if (digit === '0' && currentExpression === '0') {
    return;
  }

  // Replace single leading zero
  if (currentExpression === '0' && digit !== '.') {
    currentExpression = digit;
  } else {
    currentExpression += digit;
  }

  updateDisplay();
}

function addOperator(operator) {
  if (shouldResetOnNextInput) {
    shouldResetOnNextInput = false;
  }

  if (!currentExpression) {
    if (operator === '-') {
      currentExpression = '-';
    }
    updateDisplay();
    return;
  }

  const lastChar = getLastChar();

  // If last character is an operator, replace it
  if (isOperator(lastChar)) {
    currentExpression = currentExpression.slice(0, -1) + operator;
  } else if (lastChar !== '.') {
    currentExpression += operator;
  }

  updateDisplay();
}

function addDecimal() {
  if (shouldResetOnNextInput) {
    currentExpression = "0";
    shouldResetOnNextInput = false;
  }

  if (!currentExpression) {
    currentExpression = "0.";
  } else if (canAddDecimal() && !isOperator(getLastChar())) {
    currentExpression += ".";
  }

  updateDisplay();
}

function addParenthesis(paren) {
  if (shouldResetOnNextInput) {
    shouldResetOnNextInput = false;
  }

  if (paren === '(') {
    // Add multiplication before ( if needed
    const lastChar = getLastChar();
    if (lastChar && !isOperator(lastChar) && lastChar !== '(') {
      currentExpression += '*';
    }
    currentExpression += '(';
  } else if (paren === ')') {
    const openCount = (currentExpression.match(/\(/g) || []).length;
    const closeCount = (currentExpression.match(/\)/g) || []).length;
    if (openCount > closeCount && !isOperator(getLastChar())) {
      currentExpression += ')';
    }
  }

  updateDisplay();
}

// ================ ENHANCED CALCULATE FUNCTION WITH DISPLAY ANIMATIONS ================

function calculate() {
  if (!currentExpression) return;

  try {
    console.log('🎬 Starting calculation with cinematic effects!');

    // STEP 1: Add background calculation effect to display
    const displayEl = $('.display');
    const expressionEl = $('.expression');
    const resultEl = $('.result');

    // Remove any existing animation classes
    displayEl.classList.remove('calculating-bg', 'success-pulse', 'celebration');
    expressionEl.classList.remove('calculating');
    resultEl.classList.remove('bounce-in', 'digit-cascade', 'typewriter', 'result-glow', 'error-shake');

    // STEP 2: Start background particle animation
    displayEl.classList.add('calculating-bg');
    expressionEl.classList.add('calculating');

    console.log('🌟 Background particle animation started');

    // STEP 3: Auto-close parentheses and clean expression
    const openCount = (currentExpression.match(/\(/g) || []).length;
    const closeCount = (currentExpression.match(/\)/g) || []).length;
    let expr = currentExpression + ')'.repeat(openCount - closeCount);

    // Remove trailing operators
    expr = expr.replace(/[+\-*/%]+$/, '');

    if (!expr) return;

    // STEP 4: Calculate result
    const result = safeEvaluate(expr);
    const formattedResult = formatNumber(result);

    console.log(`🧮 Calculation complete: ${expr} = ${result}`);

    // STEP 5: Add to history
    addToHistory(currentExpression, result);

    // STEP 6: Determine animation type based on result
    let animationType = 'bounce-in'; // default
    const resultLength = formattedResult.toString().length;
    const resultValue = Math.abs(result);

    if (resultLength > 10) {
      animationType = 'typewriter'; // Long results get typewriter effect
      console.log('📝 Using typewriter animation for long result');
    } else if (resultValue > 1000000) {
      animationType = 'digit-cascade'; // Big numbers get cascade effect
      displayEl.classList.add('celebration'); // Add celebration background
      console.log('🎊 Using digit cascade + celebration for big result');
    } else if (resultValue === Math.floor(resultValue) && resultValue < 100) {
      animationType = 'bounce-in'; // Small integers get bounce
      console.log('🦘 Using bounce animation for small result');
    } else {
      animationType = 'result-glow'; // Decimals and medium numbers get glow
      console.log('✨ Using glow animation for decimal result');
    }

    // STEP 7: Apply result animation with delay for dramatic effect
    setTimeout(() => {
      currentExpression = formattedResult;
      shouldResetOnNextInput = true;

      // Update result with animation
      resultEl.textContent = formattedResult;
      resultEl.classList.add(animationType);

      // Add success pulse to entire display
      displayEl.classList.add('success-pulse');

      console.log(`🎭 Applied ${animationType} animation to result: ${formattedResult}`);

      // STEP 8: Clean up animation classes after they complete
      setTimeout(() => {
        resultEl.classList.remove(animationType);
        console.log('🧹 Cleaned up result animation classes');
      }, animationType === 'typewriter' ? 1000 : animationType === 'digit-cascade' ? 1500 : 1200);

      setTimeout(() => {
        displayEl.classList.remove('success-pulse');
      }, 1000);

    }, 500); // 500ms delay for dramatic pause

    // STEP 9: Clean up background effects
    setTimeout(() => {
      displayEl.classList.remove('calculating-bg');
      expressionEl.classList.remove('calculating');
      if (!displayEl.classList.contains('celebration')) {
        // Only remove celebration after its animation completes
        setTimeout(() => {
          displayEl.classList.remove('celebration');
        }, 2000);
      }
      console.log('🧹 Cleaned up background animation classes');
    }, 2000);

  } catch (error) {
    console.log('❌ Calculation error, showing error animation');

    // STEP 10: Error animation
    const resultEl = $('.result');
    const displayEl = $('.display');

    // Remove calculation effects
    displayEl.classList.remove('calculating-bg', 'success-pulse', 'celebration');

    // Show error with shake animation
    resultEl.classList.add('error-shake');
    showError(error.message);

    // Clean up error animation
    setTimeout(() => {
      resultEl.classList.remove('error-shake');
    }, 600);
  }
}


function clearAll() {
  currentExpression = "";
  shouldResetOnNextInput = false;
  updateDisplay();
}

function clearEntry() {
  if (!currentExpression) return;

  // Remove last character or number
  if (/\d$/.test(currentExpression)) {
    // Remove entire last number
    currentExpression = currentExpression.replace(/\d+\.?\d*$/, '');
  } else {
    // Remove last character
    currentExpression = currentExpression.slice(0, -1);
  }

  updateDisplay();
}

function backspace() {
  if (!currentExpression) return;
  currentExpression = currentExpression.slice(0, -1);
  updateDisplay();
}

// Memory functions
function memoryClear() {
  memory = 0;
  localStorage.setItem(MEMORY_KEY, "0");
}

function memoryRecall() {
  if (shouldResetOnNextInput) {
    currentExpression = "";
    shouldResetOnNextInput = false;
  }

  const lastChar = getLastChar();
  if (lastChar && !isOperator(lastChar) && lastChar !== '(') {
    currentExpression += '*';
  }

  currentExpression += memory.toString();
  updateDisplay();
}

function memoryAdd() {
  try {
    const current = currentExpression ? safeEvaluate(currentExpression) : 0;
    memory += current;
    localStorage.setItem(MEMORY_KEY, memory.toString());
  } catch {
    // Ignore errors in memory operations
  }
}

function memorySubtract() {
  try {
    const current = currentExpression ? safeEvaluate(currentExpression) : 0;
    memory -= current;
    localStorage.setItem(MEMORY_KEY, memory.toString());
  } catch {
    // Ignore errors in memory operations
  }
}

// History functions
function addToHistory(expression, result) {
  const entry = {
    expr: expression,
    result: result,
    ts: Date.now()
  };

  history.unshift(entry);
  history = history.slice(0, 100); // Keep last 100 entries
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  renderHistory();
}

function renderHistory() {
  if (!historyList) return;

  const searchTerm = historySearch?.value?.toLowerCase() || '';

  historyList.innerHTML = '';

  history
    .filter(entry =>
      !searchTerm ||
      entry.expr.toLowerCase().includes(searchTerm) ||
      entry.result.toString().toLowerCase().includes(searchTerm)
    )
    .forEach(entry => {
      const li = document.createElement('li');
      li.innerHTML = `
        <span>${entry.expr} = ${entry.result}</span>
        <button class="mini-btn" onclick="useHistoryEntry('${entry.result}')">Use</button>
      `;
      historyList.appendChild(li);
    });
}

function useHistoryEntry(result) {
  currentExpression = result;
  shouldResetOnNextInput = true;
  updateDisplay();
}

// Make useHistoryEntry global for onclick
window.useHistoryEntry = useHistoryEntry;

// Special functions
function squareRoot() {
  try {
    const current = currentExpression ? safeEvaluate(currentExpression) : 0;
    if (current < 0) {
      showError("Invalid input");
      return;
    }
    const result = Math.sqrt(current);
    currentExpression = formatNumber(result);
    shouldResetOnNextInput = true;
    updateDisplay();
  } catch {
    showError("Error");
  }
}

function reciprocal() {
  try {
    const current = currentExpression ? safeEvaluate(currentExpression) : 0;
    if (current === 0) {
      showError("Division by zero");
      return;
    }
    const result = 1 / current;
    currentExpression = formatNumber(result);
    shouldResetOnNextInput = true;
    updateDisplay();
  } catch {
    showError("Error");
  }
}

// Event handlers
function handleInput({ val, action }) {
  if (val !== undefined) {
    if (/^\d$/.test(val)) {
      addDigit(val);
    } else if (val === '.') {
      addDecimal();
    } else if (isOperator(val)) {
      addOperator(val);
    } else if (val === '(' || val === ')') {
      addParenthesis(val);
    }
    return;
  }

  switch (action) {
    case 'C': clearAll(); break;
    case 'CE': clearEntry(); break;
    case 'BACK': backspace(); break;
    case 'EQUALS': calculate(); break;
    case 'OPEN': addParenthesis('('); break;
    case 'CLOSE': addParenthesis(')'); break;
    case 'SQRT': squareRoot(); break;
    case 'RECIP': reciprocal(); break;
    case 'PERCENT': addOperator('%'); break;
    case 'MC': memoryClear(); break;
    case 'MR': memoryRecall(); break;
    case 'M+': memoryAdd(); break;
    case 'M-': memorySubtract(); break;
  }
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
  // Mic coachmark logic
  try {
    const hideCoach = localStorage.getItem('procalc:hide-mic-coach') === 'true';
    if (!hideCoach && micCoach) {
      micCoach.hidden = false;
      const closeCoach = () => {
        micCoach.style.transition = 'opacity .25s ease';
        micCoach.style.opacity = '0';
        setTimeout(() => micCoach.remove(), 250);
        localStorage.setItem('procalc:hide-mic-coach', 'true');
        const micBtn = document.getElementById('voiceToggle');
        if (micBtn) {
          micBtn.classList.add('mic-highlight');
          setTimeout(() => micBtn.classList.remove('mic-highlight'), 1500);
        }
      };
      micCoach.querySelector('.coach-close')?.addEventListener('click', closeCoach);
      // Optional auto-hide after 6s if untouched
      setTimeout(() => {
        if (document.body.contains(micCoach)) closeCoach();
      }, 6000);
    }
  } catch {}
  // Button clicks
  // ================ ENHANCED BUTTON CLICKS WITH EFFECTS ================

  // Button clicks with visual effects
  $$('.keypad .btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const val = btn.dataset.value;
      const action = btn.dataset.action;

      // Remove any existing effect classes first
      btn.classList.remove('thunder-effect', 'fire-effect', 'equals-effect', 'special-effect', 'ripple');

      // Trigger different effects based on button type
      if (val !== undefined) {
        // Number buttons get thunder effect
        if (/^\d$/.test(val)) {
          console.log(`🌩️ Thunder effect triggered for number: ${val}`);
          btn.classList.add('thunder-effect');

          // Remove effect class after animation completes
          setTimeout(() => {
            btn.classList.remove('thunder-effect');
          }, 600);
        }
        // Operator buttons get fire effect
        else if (['+', '-', '*', '/', '%'].includes(val)) {
          console.log(`🔥 Fire effect triggered for operator: ${val}`);
          btn.classList.add('fire-effect');

          // Remove effect class after animation completes
          setTimeout(() => {
            btn.classList.remove('fire-effect');
          }, 800);
        }
        // Decimal and parentheses get ripple effect
        else if (val === '.' || val === '(' || val === ')') {
          console.log(`💧 Ripple effect triggered for: ${val}`);
          btn.classList.add('ripple');

          setTimeout(() => {
            btn.classList.remove('ripple');
          }, 600);
        }
      }

      // Action buttons get special effects
      if (action !== undefined) {
        if (action === 'EQUALS') {
          console.log('🎉 Equals explosion effect triggered!');
          btn.classList.add('equals-effect');

          setTimeout(() => {
            btn.classList.remove('equals-effect');
          }, 1000);
        }
        // Function buttons (SQRT, RECIP, etc.) get purple glow
        else if (['SQRT', 'RECIP', 'PERCENT'].includes(action)) {
          console.log(`✨ Special function effect triggered for: ${action}`);
          btn.classList.add('special-effect');

          setTimeout(() => {
            btn.classList.remove('special-effect');
          }, 700);
        }
        // Clear buttons get ripple
        else if (['C', 'CE', 'BACK'].includes(action)) {
          console.log(`🧹 Clear effect triggered for: ${action}`);
          btn.classList.add('ripple');

          setTimeout(() => {
            btn.classList.remove('ripple');
          }, 600);
        }
        // Memory buttons get special glow
        else if (['MC', 'MR', 'M+', 'M-'].includes(action)) {
          console.log(`💾 Memory effect triggered for: ${action}`);
          btn.classList.add('special-effect');

          setTimeout(() => {
            btn.classList.remove('special-effect');
          }, 700);
        }
      }

      // Call the original input handler
      handleInput({ val, action });
    });
  });

  // Keyboard support
  // ================ ENHANCED KEYBOARD SUPPORT WITH EFFECTS ================

  // Keyboard support with visual effects
  document.addEventListener('keydown', (e) => {
    if (e.repeat) return;

    const key = e.key;
    let targetButton = null;

    // Find the corresponding button element for visual effects
    if (/^\d$/.test(key)) {
      targetButton = $(`.btn[data-value="${key}"]`);
      console.log(`🌩️ Keyboard thunder effect for number: ${key}`);
      if (targetButton) {
        targetButton.classList.add('thunder-effect');
        setTimeout(() => targetButton.classList.remove('thunder-effect'), 600);
      }
      handleInput({ val: key });
    } else if (['+', '-', '*', '/'].includes(key)) {
      targetButton = $(`.btn[data-value="${key}"]`);
      console.log(`🔥 Keyboard fire effect for operator: ${key}`);
      if (targetButton) {
        targetButton.classList.add('fire-effect');
        setTimeout(() => targetButton.classList.remove('fire-effect'), 800);
      }
      handleInput({ val: key });
    } else if (key === '.') {
      targetButton = $(`.btn[data-value="."]`);
      console.log('💧 Keyboard ripple effect for decimal');
      if (targetButton) {
        targetButton.classList.add('ripple');
        setTimeout(() => targetButton.classList.remove('ripple'), 600);
      }
      handleInput({ val: key });
    } else if (key === '(' || key === ')') {
      targetButton = $(`.btn[data-action="${key === '(' ? 'OPEN' : 'CLOSE'}"]`);
      console.log(`💧 Keyboard ripple effect for parenthesis: ${key}`);
      if (targetButton) {
        targetButton.classList.add('ripple');
        setTimeout(() => targetButton.classList.remove('ripple'), 600);
      }
      handleInput({ val: key });
    } else if (key === 'Enter' || key === '=') {
      targetButton = $(`.btn[data-action="EQUALS"]`);
      console.log('🎉 Keyboard equals explosion effect!');
      if (targetButton) {
        targetButton.classList.add('equals-effect');
        setTimeout(() => targetButton.classList.remove('equals-effect'), 1000);
      }
      handleInput({ action: 'EQUALS' });
    } else if (key === 'Escape') {
      targetButton = $(`.btn[data-action="C"]`);
      console.log('🧹 Keyboard clear effect');
      if (targetButton) {
        targetButton.classList.add('ripple');
        setTimeout(() => targetButton.classList.remove('ripple'), 600);
      }
      handleInput({ action: 'C' });
    } else if (key === 'Backspace') {
      targetButton = $(`.btn[data-action="BACK"]`);
      console.log('🧹 Keyboard backspace effect');
      if (targetButton) {
        targetButton.classList.add('ripple');
        setTimeout(() => targetButton.classList.remove('ripple'), 600);
      }
      handleInput({ action: 'BACK' });
    } else if (key === '%') {
      targetButton = $(`.btn[data-action="PERCENT"]`);
      console.log('✨ Keyboard percent effect');
      if (targetButton) {
        targetButton.classList.add('special-effect');
        setTimeout(() => targetButton.classList.remove('special-effect'), 700);
      }
      handleInput({ action: 'PERCENT' });
    }
  });

  // Theme toggle
  $('#themeToggle')?.addEventListener('click', () => {
    const themes = ['light', 'dark', 'amoled'];
    const current = app.dataset.theme || 'light';
    const currentIndex = themes.indexOf(current);
    const next = themes[(currentIndex + 1) % themes.length];
    app.dataset.theme = next;
    localStorage.setItem(THEME_KEY, next);
  });

  // Contrast toggle
  $('#a11yToggle')?.addEventListener('click', () => {
    const isHigh = app.dataset.contrast === 'high';
    if (isHigh) {
      delete app.dataset.contrast;
      localStorage.setItem(CONTRAST_KEY, 'normal');
    } else {
      app.dataset.contrast = 'high';
      localStorage.setItem(CONTRAST_KEY, 'high');
    }
  });

  // History toggle
  $('#historyToggle')?.addEventListener('click', () => {
    if (historyEl) {
      historyEl.hidden = !historyEl.hidden;
    }

    console.log(`🎨 Theme changed to ${next} with background effect`);
    document.body.style.transition = 'all 0.5s ease';

    // Brief theme transition effect
    setTimeout(() => {
      document.body.style.transition = '';
    }, 500);
  });

  // History search
  historySearch?.addEventListener('input', renderHistory);

  // History clear
  $('#clearHistory')?.addEventListener('click', () => {
    history = [];
    localStorage.setItem(HISTORY_KEY, '[]');
    renderHistory();
  });

  // Export functions
  $('#exportCSV')?.addEventListener('click', () => {
    const csvContent = 'Expression,Result,Time\n' +
      history.map(h => `"${h.expr}","${h.result}","${new Date(h.ts).toISOString()}"`).join('\n');
    downloadFile('history.csv', csvContent, 'text/csv');
  });

  $('#exportJSON')?.addEventListener('click', () => {
    downloadFile('history.json', JSON.stringify(history, null, 2), 'application/json');
  });

  // Initialize
  renderHistory();
  updateDisplay();
});

function downloadFile(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}


// ================ PAGE BACKGROUND INTERACTIONS ================

// Mouse-following light effect
document.addEventListener('DOMContentLoaded', () => {
  const mouseLight = document.getElementById('mouseLight');
  let mouseX = 0, mouseY = 0;
  let lightX = 0, lightY = 0;

  // Track mouse movement
  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;

    if (mouseLight) {
      mouseLight.classList.add('active');
    }
  });

  // Smooth light following animation
  function animateLight() {
    // Smooth interpolation for natural movement
    lightX += (mouseX - lightX) * 0.1;
    lightY += (mouseY - lightY) * 0.1;

    if (mouseLight) {
      mouseLight.style.transform = `translate(${lightX - 100}px, ${lightY - 100}px)`;
    }

    requestAnimationFrame(animateLight);
  }

  animateLight();

  // Hide light when mouse leaves window
  document.addEventListener('mouseleave', () => {
    if (mouseLight) {
      mouseLight.classList.remove('active');
    }
  });

  console.log('🌟 Background mouse light effect initialized');
});

// Background effects for calculations
function triggerCalculationBackground() {
  console.log('🎆 Triggering calculation background effect');
  document.body.classList.add('calculating');

  setTimeout(() => {
    document.body.classList.remove('calculating');
    document.body.classList.add('success-calculation');

    setTimeout(() => {
      document.body.classList.remove('success-calculation');
    }, 2000);
  }, 1000);
}

// Add background effects to existing calculate function
// FIND your existing calculate() function and ADD this line after "console.log('🧮 Calculation complete...')"
// ADD: triggerCalculationBackground();

// ================ R​ANDOM PARTICLE SPAWNER ================

document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('particle-container');
  const PARTICLE_COUNT = 10;      // Total dots
  const MIN_DURATION = 5;        // seconds
  const MAX_DURATION = 10;        // seconds

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const p = document.createElement('div');
    p.classList.add('particle');

    // Random start position within viewport
    const startX = Math.random() * 100; // percent
    const startY = Math.random() * 100;

    // Random movement vector (dx, dy) up to ±50vw/h
    const dx = (Math.random() - 0.5) * 100 + 'vw';
    const dy = (Math.random() - 0.5) * 100 + 'vh';

    // Random duration between min/max
    const dur = (MIN_DURATION + Math.random() * (MAX_DURATION - MIN_DURATION)) + 's';

    // Random delay so they don't all start together
    const delay = (Math.random() * MAX_DURATION) + 's';

    // Set inline CSS vars and animation settings
    p.style.setProperty('--dx', dx);
    p.style.setProperty('--dy', dy);
    p.style.animationDuration = `1s, ${dur}`;     // first for fade-in, second for move
    p.style.animationDelay = `0s, ${delay}`;   // fade-in starts immediately; move after delay

    // Position via inline style (percent)
    p.style.left = startX + '%';
    p.style.top = startY + '%';

    container.appendChild(p);
  }

  console.log('✨ Random particles initialized');
});




// ================ CUSTOM CURSOR & SPARKLES LOGIC ================

document.addEventListener('DOMContentLoaded', () => {
  const cursor = document.getElementById('custom-cursor');
  const sparkles = document.getElementById('cursor-sparkles');

  // Track mouse movement
  document.addEventListener('mousemove', (e) => {
    cursor.style.left = e.clientX + 'px';
    cursor.style.top = e.clientY + 'px';
  });

  // Click animation and sparkles
  document.addEventListener('click', (e) => {
    // Animate cursor orb
    cursor.classList.add('click-animate');
    setTimeout(() => cursor.classList.remove('click-animate'), 400);

    // Generate sparkles
    for (let i = 0; i < 8; i++) {
      const sparkle = document.createElement('div');
      sparkle.classList.add('sparkle');

      // Random direction & distance
      const angle = Math.random() * Math.PI * 2;
      const dist = 20 + Math.random() * 20; // px
      const sx = Math.cos(angle) * dist + 'px';
      const sy = Math.sin(angle) * dist + 'px';

      sparkle.style.left = e.clientX + 'px';
      sparkle.style.top = e.clientY + 'px';
      sparkle.style.setProperty('--sx', sx);
      sparkle.style.setProperty('--sy', sy);

      sparkles.appendChild(sparkle);
      // Remove after animation
      sparkle.addEventListener('animationend', () => sparkle.remove());
    }
  });
});


if ("ontouchstart" in document.documentElement) {
  const cursor = document.getElementById('custom-cursor');
  if (cursor) cursor.style.display = 'none';
}
