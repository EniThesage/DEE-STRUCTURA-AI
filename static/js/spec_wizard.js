document.addEventListener('DOMContentLoaded', function () {
  const steps = Array.from(document.querySelectorAll('.wizard-step'));
  const pills = Array.from(document.querySelectorAll('.step-pill'));
  const backBtn = document.getElementById('wizard-back');
  const nextBtn = document.getElementById('wizard-next');
  const submitBtn = document.getElementById('wizard-submit');

  function showStep(index) {
    steps.forEach(function (step, i) {
      step.classList.toggle('active', i === index);
    });
    pills.forEach(function (pill, i) {
      pill.classList.toggle('active', i === index);
    });
    backBtn.style.visibility = index === 0 ? 'hidden' : 'visible';
    nextBtn.style.display = index === steps.length - 1 ? 'none' : 'inline-block';
    submitBtn.style.display = index === steps.length - 1 ? 'inline-block' : 'none';
  }

  function currentIndex() {
    return steps.findIndex(function (step) {
      return step.classList.contains('active');
    });
  }

  backBtn.addEventListener('click', function () {
    const index = currentIndex();
    if (index > 0) showStep(index - 1);
  });

  nextBtn.addEventListener('click', function () {
    const index = currentIndex();
    if (index < steps.length - 1) showStep(index + 1);
  });

  pills.forEach(function (pill, index) {
    pill.addEventListener('click', function () {
      showStep(index);
    });
  });

  const firstErrorStep = steps.findIndex(function (step) {
    return step.querySelector('.errorlist');
  });

  showStep(firstErrorStep >= 0 ? firstErrorStep : 0);
});
