'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const clearPrivate = () => $$('[data-private]').forEach(input => { input.value = ''; });
window.addEventListener('pagehide', clearPrivate);
window.addEventListener('pageshow', event => { if (event.persisted) clearPrivate(); });
$$('[data-toggle-password]').forEach(button => button.addEventListener('click', () => {
  const input = document.getElementById(button.dataset.togglePassword);
  const visible = input.type === 'password';
  input.type = visible ? 'text' : 'password';
  button.textContent = visible ? 'Hide' : 'Show';
  button.setAttribute('aria-pressed', String(visible));
}));
$$('[data-guide-dialog]').forEach(link => link.addEventListener('click', event => {
  const dialog = $('#screening-guide');
  if (dialog && typeof dialog.showModal === 'function') {
    event.preventDefault();
    dialog.showModal();
  }
}));
$$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$$('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  if (event.target === dialog) {
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  }
}));
$$('[data-report-level]').forEach(input => input.addEventListener('change', () => {
  const dependents = {state:['district','school','group'], district:['school','group'], school_query:['school','group'], school:['group']};
  (dependents[input.dataset.reportLevel] || []).forEach(name => {
    const field = $(`[name="${name}"]`, input.form);
    if (field) field.value = '';
  });
}));
$$('[data-print]').forEach(button => button.addEventListener('click', () => window.print()));
$$('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const value = document.getElementById(button.dataset.copy).value;
  try { await navigator.clipboard.writeText(value); $('#copy-status').textContent = ' Copied to clipboard.'; }
  catch {
    const field = document.getElementById(button.dataset.copy);
    if (field.closest('details')) field.closest('details').open = true;
    field.focus(); field.select();
    $('#copy-status').textContent = ' Select the invitation text and copy it manually.';
  }
}));

const screening = $('#screening-form');
if (screening) {
  const value = key => $(`[name="${key}"]`, screening)?.value;
  const show = (key, visible) => {
    const wrapper = $(`[data-field="${key}"]`, screening);
    if (!wrapper) return;
    wrapper.hidden = !visible;
    $$('input,select', wrapper).forEach(input => { input.disabled = !visible; });
  };
  const update = () => {
    const dob = value('dob'), day = screening.dataset.screeningDate;
    let months = null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(dob)) {
      const [y,m,d] = dob.split('-').map(Number), [sy,sm,sd] = day.split('-').map(Number);
      months = (sy-y)*12+sm-m-(sd<d ? 1 : 0);
    }
    show('muac', months !== null && months < 60);
    const adolescent = months !== null && months >= 120 && value('sex') === 'female';
    $('#section-C2').hidden = !adolescent;
    show('menarche', adolescent);
    const menstruating = adolescent && value('menarche') === 'yes';
    ['menarche_age','pads','clots','cycle','bleeding_days'].forEach(key => show(key, menstruating));
    show('egg', ['ovo','nonveg'].includes(value('diet_type')));
    show('meat', value('diet_type') === 'nonveg');
    show('deworming_date', value('deworming') === 'yes');
    const height = Number(value('height')), weight = Number(value('weight'));
    let preview = 'Enter date of birth and measurements to see the age and BMI.';
    if (months !== null && months >= 0) {
      preview = `Age: ${Math.floor(months/12)} years, ${months%12} months (${months} months).`;
      if (months < 60) preview += ' Record the MUAC tape colour; BMI is not calculated under 5.';
      else if (height > 0 && weight > 0) preview += ` BMI: ${(weight/(height/100)**2).toFixed(2)} kg/m². Age- and sex-specific scoring is calculated when saved.`;
    }
    $('#growth-preview').textContent = preview;
  };
  screening.addEventListener('change', update);
  screening.addEventListener('input', update);
  update();
  screening.addEventListener('submit', async event => {
    event.preventDefault();
    const button = $('button[type="submit"]', screening);
    if (button.disabled) return;
    const data = new FormData(screening);
    button.disabled = true;
    const original = button.textContent;
    button.textContent = 'Saving…';
    $$('.client-save-error', screening).forEach(n => n.remove());
    try {
      const response = await fetch(location.href, {method:'POST', body:data, credentials:'same-origin'});
      if (!response.ok) throw new Error('Could not save. Your answers remain on this page. Please try again.');
      if (response.redirected) {
        if (new URL(response.url).pathname === '/login/') throw new Error('Your session has expired. Sign in in another tab, then retry. Your answers remain on this page.');
        location.assign(response.url); return;
      }
      const doc = new DOMParser().parseFromString(await response.text(),'text/html');
      const error = $('.flash.error', doc);
      if (error) {
        const old = $('.flash.error', screening); if (old) old.remove();
        const fresh = document.importNode(error,true); fresh.classList.add('client-save-error'); screening.prepend(fresh);
        $$('[data-field]', screening).forEach(el => { el.classList.remove('has-error'); $$('.errorlist', el).forEach(e=>e.remove()); });
        $$('[data-field].has-error', doc).forEach(el => {
          const target = $(`[data-field="${el.dataset.field}"]`,screening); if (!target) return;
          target.classList.add('has-error'); const list = $('.errorlist',el); if (list) target.append(document.importNode(list,true));
        });
        fresh.scrollIntoView({behavior:'smooth',block:'center'});
      } else throw new Error('Your session may have expired. Open the sign-in page in another tab, then retry.');
    } catch(error) {
      const message = document.createElement('div'); message.className='flash error client-save-error'; message.setAttribute('role','alert'); message.textContent=error.message; screening.prepend(message); message.scrollIntoView({behavior:'smooth'});
    } finally { button.disabled=false; button.textContent=original; }
  });
}

function normaliseIndianMobile(value) {
  const compact = value.trim().replace(/[\s()-]/g, '');
  if (/^[6-9]\d{9}$/.test(compact)) return `91${compact}`;
  const international = compact.match(/^\+?91([6-9]\d{9})$/);
  return international ? `91${international[1]}` : null;
}
const notify = $('#notify-form');
if (notify) {
  const data = JSON.parse($('#notify-data').textContent);
  const openButton = $('#open-whatsapp');
  openButton.disabled = !data.ready;
  let openedInThisPage = false;
  const message = () => {
    const values = {...data.values, parent:$('#parent-name').value.trim()};
    return data.template.replace(/\{(parent|school|class|section|roll|findings|next_date|video)\}/g, (_, key) => values[key] ?? '');
  };
  const saveStatus = async () => {
    if (!openedInThisPage) return;
    try {
      const response = await fetch(data.record_url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':$('[name="csrfmiddlewaretoken"]',notify).value,'Content-Type':'application/json'},body:'{}'});
      if (!response.ok) throw new Error('status');
      $('#retry-status').hidden=true;
      location.assign(data.return_url);
    } catch {
      $('#notify-status').className='flash error'; $('#notify-status').textContent='WhatsApp opened, but NutriLift could not save the status. Retry saving below.'; $('#retry-status').hidden=false;
    }
  };
  $('#retry-status').addEventListener('click',saveStatus);
  notify.addEventListener('submit', async event => {
    event.preventDefault();
    if (!data.ready) { $('#notify-status').textContent='The programme team must approve the message and video before sharing.'; return; }
    if (openedInThisPage) return;
    const phone=normaliseIndianMobile($('#parent-phone').value);
    if (!phone) { $('#notify-status').textContent='Enter a 10-digit Indian mobile number, with or without +91.'; $('#parent-phone').focus(); return; }
    const url=`https://wa.me/${phone}?text=${encodeURIComponent(message())}`;
    const popup=window.open('about:blank','_blank');
    if (!popup) { $('#notify-status').textContent='The browser blocked WhatsApp. Allow pop-ups and try again. The status remains pending.'; return; }
    try { popup.opener=null; popup.location.replace(url); }
    catch { popup.close(); $('#notify-status').textContent='WhatsApp could not be opened. The status remains pending.'; return; }
    openedInThisPage=true;
    openButton.disabled = true;
    clearPrivate();
    await saveStatus();
  });
  $$('[data-clear-private]').forEach(a=>a.addEventListener('click',clearPrivate));
  window.addEventListener('pageshow', event => {
    if (event.persisted) { openedInThisPage=false; openButton.disabled=!data.ready; $('#retry-status').hidden=true; }
  });
}

const inviteForm=$('#invite-form');
if(inviteForm) inviteForm.addEventListener('submit',event=>{
  event.preventDefault();
  const phone=normaliseIndianMobile($('#invite-phone').value);
  if(!phone){ $('#invite-status').textContent='Enter a 10-digit Indian mobile number, with or without +91.'; $('#invite-phone').focus(); return; }
  const name=$('#invite-name').value.trim();
  const text=name ? $('#invitation').value.replace('Hello,',`Hello ${name},`) : $('#invitation').value;
  const popup=window.open('about:blank','_blank');
  if(!popup){$('#invite-status').textContent='Please allow pop-ups and try again.';return;}
  popup.opener=null;popup.location.replace(`https://wa.me/${phone}?text=${encodeURIComponent(text)}`);clearPrivate();
  $('#invite-status').textContent='WhatsApp opened. Check the recipient and press Send.';
});
