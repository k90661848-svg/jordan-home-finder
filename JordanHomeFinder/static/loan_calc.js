/**
 * Loan Calculator - client-side, property-aware.
 * Initialize with: LoanCalc.init({ propertyPrice: 200000, downPct: 20, downPctInputId: 'down_pct' })
 * Or: LoanCalc.init({ propertyPrice: 200000 })
 */
(function () {
  "use strict";

  var config = {
    propertyPrice: 2000,
    downPct: 20,
    downPctInputId: null,
    amountStep: 5000,
    amountMin: 500,
    amountMax: 2000000,
    yearsMin: 1,
    yearsMax: 30,
    yearsDefault: 20,
    interestMin: 0,
    interestMax: 25,
    interestDefault: 7.99,
    interestStep: 0.25
  };

  function formatJD(n) {
    return "JD " + Number(n).toLocaleString("en-JO", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function calcMonthly(amount, ratePct, years) {
    if (amount <= 0) return 0;
    var r = ratePct / 100 / 12;
    var n = years * 12;
    return amount * (r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
  }

  function updateDisplay(state) {
    var monthly = calcMonthly(state.amount, state.interest, state.years);
    var total = monthly * state.years * 12;
    var elCalc = document.getElementById("loan-calc-calculated");
    var elMonthly = document.getElementById("loan-calc-monthly");
    var elTotal = document.getElementById("loan-calc-total");
    if (elCalc) elCalc.textContent = state.interest + "% yearly interest";
    if (elMonthly) elMonthly.textContent = formatJD(monthly);
    if (elTotal) elTotal.textContent = formatJD(total);
  }

  function syncFromDownPct() {
    if (!config.downPctInputId) return;
    var inp = document.getElementById(config.downPctInputId);
    if (!inp) return;
    var pct = parseFloat(inp.value) || 20;
    var loan = Math.round(config.propertyPrice * (1 - pct / 100) / config.amountStep) * config.amountStep;
    loan = Math.max(config.amountMin, Math.min(config.amountMax, loan));
    var slider = document.getElementById("loan-calc-amount");
    var num = document.getElementById("loan-calc-amount-val");
    if (slider) { slider.value = loan; }
    if (num) { num.value = loan; }
  }

  function clampAmount(val) {
    return Math.max(config.amountMin, Math.min(config.amountMax, Math.round(val)));
  }

  function clampYears(val) {
    return Math.max(config.yearsMin, Math.min(config.yearsMax, Math.round(val)));
  }

  function clampInterest(val) {
    return Math.max(config.interestMin, Math.min(config.interestMax, Math.round(val * 100) / 100));
  }

  function setupSlider(id, valId, min, max, step, defaultValue, onChange) {
    var slider = document.getElementById(id);
    var num = document.getElementById(valId);
    if (!slider || !num) return;

    slider.min = min;
    slider.max = max;
    slider.step = step;
    slider.value = defaultValue;
    num.value = String(defaultValue);

    slider.addEventListener("input", function () {
      var v = parseFloat(this.value) || defaultValue;
      num.value = v;
      onChange();
    });

    num.addEventListener("input", function () {
      var v = parseFloat(this.value) || defaultValue;
      if (id === "loan-calc-amount") v = clampAmount(v);
      else if (id === "loan-calc-years") v = clampYears(v);
      else if (id === "loan-calc-interest") v = clampInterest(v);
      num.value = v;
      slider.value = v;
      onChange();
    });

    num.addEventListener("change", function () {
      var v = parseFloat(this.value) || defaultValue;
      if (id === "loan-calc-amount") v = clampAmount(v);
      else if (id === "loan-calc-years") v = clampYears(v);
      else if (id === "loan-calc-interest") v = clampInterest(v);
      num.value = v;
      slider.value = v;
      onChange();
    });
  }

  function setupButtons(amountId, minusId, plusId, step, clampFn) {
    var num = document.getElementById(amountId);
    var minus = document.getElementById(minusId);
    var plus = document.getElementById(plusId);
    if (!num || !minus || !plus) return;

    minus.addEventListener("click", function () {
      var v = parseFloat(num.value) || 0;
      v = clampFn(v - step);
      num.value = v;
      var slider = document.getElementById(amountId.replace("-val", ""));
      if (slider) slider.value = v;
      window.LoanCalcUpdate && window.LoanCalcUpdate();
    });

    plus.addEventListener("click", function () {
      var v = parseFloat(num.value) || 0;
      v = clampFn(v + step);
      num.value = v;
      var slider = document.getElementById(amountId.replace("-val", ""));
      if (slider) slider.value = v;
      window.LoanCalcUpdate && window.LoanCalcUpdate();
    });
  }

  function getState() {
    var amount = parseInt(document.getElementById("loan-calc-amount-val") && document.getElementById("loan-calc-amount-val").value, 10) || config.amountMin;
    var years = parseInt(document.getElementById("loan-calc-years-val") && document.getElementById("loan-calc-years-val").value, 10) || config.yearsDefault;
    var interest = parseFloat(document.getElementById("loan-calc-interest-val") && document.getElementById("loan-calc-interest-val").value) || config.interestDefault;
    return { amount: amount, years: years, interest: interest };
  }

  function update() {
    var state = getState();
    updateDisplay(state);
  }

  window.LoanCalcUpdate = update;

  window.LoanCalc = {
    init: function (opts) {
      opts = opts || {};
      config.propertyPrice = opts.propertyPrice || 2000;
      config.downPct = opts.downPct || 20;
      config.downPctInputId = opts.downPctInputId || null;
      config.yearsDefault = opts.yearsDefault !== undefined ? opts.yearsDefault : 20;
      config.interestDefault = opts.interestDefault !== undefined ? opts.interestDefault : 7.99;

      var defaultLoan = Math.round(config.propertyPrice * (1 - config.downPct / 100) / config.amountStep) * config.amountStep;
      defaultLoan = clampAmount(defaultLoan);

      var onChange = function () {
        update();
      };

      setupSlider("loan-calc-amount", "loan-calc-amount-val", config.amountMin, config.amountMax, config.amountStep, defaultLoan, onChange);
      setupSlider("loan-calc-years", "loan-calc-years-val", config.yearsMin, config.yearsMax, 1, config.yearsDefault, onChange);
      setupSlider("loan-calc-interest", "loan-calc-interest-val", config.interestMin, config.interestMax, config.interestStep, config.interestDefault, onChange);

      setupButtons("loan-calc-amount-val", "loan-calc-amount-minus", "loan-calc-amount-plus", config.amountStep, clampAmount);
      setupButtons("loan-calc-years-val", "loan-calc-years-minus", "loan-calc-years-plus", 1, clampYears);
      setupButtons("loan-calc-interest-val", "loan-calc-interest-minus", "loan-calc-interest-plus", config.interestStep, clampInterest);

      if (config.downPctInputId) {
        var inp = document.getElementById(config.downPctInputId);
        if (inp) {
          inp.addEventListener("input", function () {
            syncFromDownPct();
            update();
          });
          inp.addEventListener("change", function () {
            syncFromDownPct();
            update();
          });
        }
      }

      update();
    }
  };
})();
