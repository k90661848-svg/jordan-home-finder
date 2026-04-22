(function () {
  var wrap = document.getElementById('property-slideshow');
  if (!wrap) return;

  var track = wrap.querySelector('.slideshow-track');
  var slides = wrap.querySelectorAll('.slideshow-slide');
  var prevBtn = wrap.querySelector('.slideshow-prev');
  var nextBtn = wrap.querySelector('.slideshow-next');
  var dotsContainer = wrap.querySelector('.slideshow-dots');

  if (slides.length <= 1) return;

  var current = 0;
  var total = slides.length;

  function goTo(index) {
    current = (index + total) % total;
    if (track) track.style.transform = 'translateX(-' + current * 100 + '%)';
    slides.forEach(function (s, i) { s.setAttribute('aria-hidden', i !== current); });
    var dots = wrap.querySelectorAll('.slideshow-dot');
    dots.forEach(function (d, i) { d.classList.toggle('active', i === current); });
  }

  if (dotsContainer) {
    for (var i = 0; i < total; i++) {
      var dot = document.createElement('button');
      dot.type = 'button';
      dot.className = 'slideshow-dot' + (i === 0 ? ' active' : '');
      dot.setAttribute('aria-label', 'Slide ' + (i + 1));
      dot.addEventListener('click', function (j) { return function () { goTo(j); }; }(i));
      dotsContainer.appendChild(dot);
    }
  }

  if (prevBtn) prevBtn.addEventListener('click', function () { goTo(current - 1); });
  if (nextBtn) nextBtn.addEventListener('click', function () { goTo(current + 1); });

  goTo(0);
})();
