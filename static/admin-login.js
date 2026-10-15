document.getElementById('login').onsubmit = async event => {
  event.preventDefault();
  const button = event.target.querySelector('button'); button.disabled = true;
  try {
    const response = await fetch('/admin/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password:document.getElementById('password').value})});
    if (response.ok) { location.replace('/admin'); return; }
    const result = await response.json(); document.getElementById('error').textContent = result.error || 'Sign-in failed.';
  } catch { document.getElementById('error').textContent = 'Unable to connect. Try again.'; }
  finally { button.disabled = false; }
};
