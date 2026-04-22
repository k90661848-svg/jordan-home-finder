/**
 * Finance engine: loan calculator, affordability (DTI), savings planner, scenario presets.
 * Use: FinanceEngine.init() or FinanceEngine.calcLoan(principal, ratePct, years)
 */
(function () {
  "use strict";

  function monthlyPayment(principal, annualRatePct, years) {
    if (principal <= 0 || years <= 0) return 0;
    var r = annualRatePct / 100 / 12;
    var n = years * 12;
    if (r < 1e-10) return principal / n;
    return principal * (r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
  }

  function totalInterest(principal, monthlyPmt, years) {
    return Math.max(0, monthlyPmt * years * 12 - principal);
  }

  function dtiRisk(dtiPct) {
    if (dtiPct < 30) return { level: "safe", label: "Safe" };
    if (dtiPct < 40) return { level: "moderate", label: "Moderate" };
    if (dtiPct < 50) return { level: "risky", label: "Risky" };
    return { level: "not_recommended", label: "Not recommended" };
  }

  function bindSliders(config) {
    var ids = config.ids || {};
    var onUpdate = config.onUpdate || function () {};
    var getValues = config.getValues;
    if (!getValues) return;

    function fire() {
      var v = getValues();
      if (v) onUpdate(v);
    }

    ["amount", "years", "interest"].forEach(function (key) {
      var sliderId = ids[key + "Slider"];
      var valId = ids[key + "Val"];
      if (!sliderId || !valId) return;
      var slider = document.getElementById(sliderId);
      var valEl = document.getElementById(valId);
      if (!slider || !valEl) return;
      slider.addEventListener("input", function () {
        valEl.value = this.value;
        fire();
      });
      valEl.addEventListener("input", function () {
        var n = parseFloat(this.value);
        if (!isNaN(n)) {
          slider.value = n;
          fire();
        }
      });
    });
  }

  window.FinanceEngine = {
    calcLoan: function (principal, ratePct, years) {
      var monthly = monthlyPayment(principal, ratePct, years);
      var total = monthly * years * 12;
      var interest = totalInterest(principal, monthly, years);
      return { monthly: monthly, total: total, totalInterest: interest };
    },
    dti: function (debt, payment, income) {
      if (!income || income <= 0) return { pct: 0, risk: dtiRisk(0) };
      var pct = ((debt + payment) / income) * 100;
      return { pct: pct, risk: dtiRisk(pct) };
    },
    savingsTarget: function (goal, currentSavings, targetMonths) {
      var remaining = Math.max(0, goal - currentSavings);
      if (!targetMonths || targetMonths <= 0) return { remaining: remaining, monthly: 0 };
      return { remaining: remaining, monthly: remaining / targetMonths };
    },
    bindSliders: bindSliders,
    init: function (opts) {
      opts = opts || {};
      var container = opts.container || document;
      var monthlyEl = container.querySelector(opts.monthlyEl || "#finance-monthly");
      var totalEl = container.querySelector(opts.totalEl || "#finance-total");
      var interestEl = container.querySelector(opts.interestEl || "#finance-total-interest");
      var getValues = opts.getValues || function () {
        var p = parseFloat(document.getElementById(opts.ids && opts.ids.amountVal)?.value) || 0;
        var r = parseFloat(document.getElementById(opts.ids && opts.ids.interestVal)?.value) || 7.5;
        var y = parseInt(document.getElementById(opts.ids && opts.ids.yearsVal)?.value, 10) || 25;
        return { principal: p, rate: r, years: y };
      };
      var onUpdate = function (v) {
        var res = window.FinanceEngine.calcLoan(v.principal, v.rate, v.years);
        if (monthlyEl) monthlyEl.textContent = formatNum(res.monthly);
        if (totalEl) totalEl.textContent = formatNum(res.total);
        if (interestEl) interestEl.textContent = formatNum(res.totalInterest);
      };
      bindSliders({ ids: opts.ids, getValues: getValues, onUpdate: onUpdate });
      var v = getValues();
      if (v && v.principal > 0) onUpdate(v);
    }
  };

  function formatNum(n) {
    return (typeof n === "number" && !isNaN(n)) ? "JD " + Math.round(n).toLocaleString() : "JD 0";
  }
})();
