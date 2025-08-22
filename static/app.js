    // (fsIndex, fsImages) are now declared at top-level scope
// Helpers
function getName() {
  return localStorage.getItem('raterName') || '';
}
function setName(name) {
  localStorage.setItem('raterName', name.trim());
}
function starHTML(value, current) {
  let html = '';
  for (let i=1;i<=5;i++) {
    const filled = i <= current ? 'filled' : '';
    html += `<span class="star ${filled}" data-value="${i}">★</span>`;
  }
  return html;
}
async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error('Failed: ' + res.status);
  return res.json();
}
async function postJSON(url, data) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || ('Failed: ' + res.status));
  }
  return res.json();
}

// Admin page logic
async function loadStats() {
  try {
  // respect selected set in admin UI (stats selector takes precedence)
  const statsSel = document.getElementById('stats-set-select');
  const setSelect = document.getElementById('set-select');
  const sel = statsSel?.value ? statsSel : setSelect;
  const setParam = sel?.value ? ('?set=' + encodeURIComponent(sel.value)) : '';
    const data = await fetchJSON('/api/images' + setParam);
    const tbody = document.querySelector('#stats-table tbody');
    if (!tbody) return;
  // remember which set is currently shown
  tbody.dataset.currentSet = sel?.value || '';
  tbody.innerHTML = '';
    for (const img of data.images) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
  <td><img src="${img.url}" alt=""></td>
  <td>${img.filename}</td>
  <td>${img.set_name ? `<span class="muted">${img.set_name}</span>` : ''}</td>
  <td>${img.avg_rating?.toFixed(2) ?? '-'}<\/td>
  <td>${img.rating_count}<\/td>
        <td>
          <button class="hide-photo" data-id="${img.id}" style="background:#ecc94b; color:#222;">${img.hidden ? 'Unhide' : 'Hide'}</button>
          <button class="delete-photo" data-id="${img.id}" style="background:#e53e3e; color:white;">Delete</button>
        </td>
      `;
      tbody.appendChild(tr);
    }
  } catch (e) {
    console.error(e);
  }
}
async function loadTop() {
  const n = parseInt(document.getElementById('top-n').value || '5', 10);
  const tbody = document.querySelector('#stats-table tbody');
  if (!tbody) return;
  try {
  // if stats set selector has a value, include it
  const statsSel = document.getElementById('stats-set-select');
  const setParam = statsSel?.value ? ('&set=' + encodeURIComponent(statsSel.value)) : '';
  // ensure we build a valid querystring
  const data = await fetchJSON('/api/top?limit='+n + setParam);
    tbody.innerHTML = '';
    for (const img of data.images) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><img src="${img.url}" alt=""></td>
        <td>${img.filename}</td>
        <td>${img.avg_rating?.toFixed(2) ?? '-'}</td>
        <td>${img.rating_count}</td>
      `;
      tbody.appendChild(tr);
    }
  } catch (e) {
    console.error(e);
  }
}
async function handleUpload(e) {
  e.preventDefault();
  const form = e.target;
  const files = document.getElementById('file-input').files;
  if (!files || !files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('photos', f);
  // include selected set
  const setSel = document.getElementById('set-select');
  if (setSel && setSel.value) fd.append('set', setSel.value);
  const status = document.getElementById('upload-status');
  status.textContent = 'Uploading...';
  const res = await fetch('/upload', { method: 'POST', body: fd });
  if (!res.ok) {
    status.textContent = 'Upload failed.';
    return;
  }
  status.textContent = 'Uploaded!';
  document.getElementById('file-input').value = '';
  loadStats();
}

// Gallery logic
async function loadGallery() {
  const nameInput = document.getElementById('rater-name');
  if (nameInput) nameInput.value = getName();
  await populateUserDropdown();
  // populate gallery set selector
  const gallerySet = document.getElementById('gallery-set-select');
  if (gallerySet && !gallerySet.dataset.loaded) {
    try {
      const data = await fetchJSON('/api/sets');
      gallerySet.innerHTML = '';
      for (const s of data.sets) {
        const opt = document.createElement('option');
        opt.value = s.slug;
        opt.textContent = s.name;
        gallerySet.appendChild(opt);
      }
      gallerySet.dataset.loaded = '1';
      gallerySet.onchange = () => loadGallery();
    } catch (e) {
      console.error('Failed to load gallery sets', e);
    }
  }

  const sortBy = document.getElementById('sort-by').value;
  const topFilter = parseInt(document.getElementById('top-filter').value || '0', 10);

  const name = encodeURIComponent(getName());
  let url = '/api/images?include_user_rating=1';
  const gallerySetSel = document.getElementById('gallery-set-select');
  if (gallerySetSel && gallerySetSel.value) url += '&set=' + encodeURIComponent(gallerySetSel.value);
  if (name) url += '&user=' + name;
  const data = await fetchJSON(url);
  let images = data.images;

  // sort
  if (sortBy === 'avg_desc') {
    images.sort((a,b) => (b.avg_rating || 0) - (a.avg_rating || 0));
  } else if (sortBy === 'count_desc') {
    images.sort((a,b) => (b.rating_count || 0) - (a.rating_count || 0));
  } else {
    images.sort((a,b) => b.created_at.localeCompare(a.created_at)); // newest
  }

  if (topFilter > 0) images = images.slice(0, topFilter);

  const grid = document.getElementById('gallery');
  if (!grid) return;
  grid.innerHTML = '';
  for (const [i, img] of images.entries()) {
    const userRating = img.user_rating || 0;
    const card = document.createElement('div');
    card.className = 'card-img';
    card.innerHTML = `
      <img src="${img.url}" alt="${img.filename}">
      <div class="meta">
        <div class="muted">${img.filename}</div>
      </div>
      <div class="stars" data-image-id="${img.id}">
        ${starHTML(5, userRating)}
      </div>
    `;
    // Double-click to start fullscreen at this image
    card.addEventListener('dblclick', () => {
      // Gather images from gallery for fullscreen
      fsImages = Array.from(document.querySelectorAll('#gallery .card-img')).map(card => {
        const imgEl = card.querySelector('img');
        const id = card.querySelector('.stars').dataset.imageId;
        const userRating = card.querySelectorAll('.star.filled').length;
        return {
          url: imgEl.src,
          filename: imgEl.alt,
          id: parseInt(id, 10),
          user_rating: userRating
        };
      });
      document.getElementById('fullscreen-view').style.display = 'flex';
  showFSImage(i);
      document.body.style.overflow = 'hidden';
    });
    grid.appendChild(card);
  }

  // star click handlers
  for (const stars of document.querySelectorAll('.stars')) {
    stars.addEventListener('click', async (ev) => {
      const el = ev.target;
      if (!el.classList.contains('star')) return;
      const rating = parseInt(el.dataset.value, 10);
      const imageId = parseInt(stars.dataset.imageId, 10);
      const name = getName().trim();
      if (!name) {
        alert('Please enter your name (top left) and click Save.');
        return;
      }
      try {
        await postJSON('/api/rate', { image_id: imageId, user: name, rating });
        // update UI: fill stars
        for (const s of stars.querySelectorAll('.star')) {
          const v = parseInt(s.dataset.value, 10);
          s.classList.toggle('filled', v <= rating);
        }
        // refresh the card's meta with new avg/count
        await refreshCardMeta(imageId, stars.closest('.card-img').querySelector('.meta'));
      } catch (e) {
        alert('Rating failed: ' + e.message);
      }
    });
  }
}

async function populateUserDropdown() {
  const userDropdown = document.getElementById('user-dropdown');
  const nameInput = document.getElementById('rater-name');
  if (userDropdown) {
    const res = await fetchJSON('/api/all_users');
    userDropdown.innerHTML = '';
    for (const user of res.users) {
      const opt = document.createElement('option');
      opt.value = user;
      opt.textContent = user;
      userDropdown.appendChild(opt);
    }
    // If current name not in dropdown, add it
    const currentName = getName();
    if (currentName && !res.users.includes(currentName)) {
      const opt = document.createElement('option');
      opt.value = currentName;
      opt.textContent = currentName;
      userDropdown.appendChild(opt);
    }
    userDropdown.value = currentName;
    userDropdown.onchange = () => {
      setName(userDropdown.value);
      if (nameInput) nameInput.value = userDropdown.value;
      loadGallery();
    };
  }
}
async function refreshCardMeta(imageId, metaEl) {
  const data = await fetchJSON('/api/images?id=' + imageId);
  const img = data.images[0];
  if (img && metaEl) {
    metaEl.innerHTML = `<div><strong>${img.avg_rating?.toFixed(2) ?? '-'}</strong> avg • ${img.rating_count} votes</div>
                        <div class="muted">${img.filename}</div>`;
  }
}

// Wire up
window.addEventListener('DOMContentLoaded', () => {
  // Yes/No voting in fullscreen
  const fsYesBtn = document.getElementById('fs-yes');
  const fsNoBtn = document.getElementById('fs-no');
  if (fsYesBtn && fsNoBtn) {
    fsYesBtn.addEventListener('click', () => rateFSYesNo('Yes'));
    fsNoBtn.addEventListener('click', () => rateFSYesNo('No'));
  }

  // Function to handle Yes/No rating in fullscreen
  window.rateFSYesNo = async function(value) {
    const img = fsImages[fsIndex];
    const user = getName();
    if (!img || !user) return;
    try {
      await postJSON('/api/rate_yesno', { image_id: img.id, user, value });
      document.getElementById('fs-rating').textContent = `You voted: ${value}`;
      setTimeout(() => {
        showFSImage(fsIndex + 1);
      }, 400);
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }
  // Listen for rating type switch in admin panel
  const ratingTypeSelect = document.getElementById('rating-type');
  if (ratingTypeSelect) {
    ratingTypeSelect.addEventListener('change', () => {
      const type = ratingTypeSelect.value;
      localStorage.setItem('ratingType', type);
      updateRatingUI(type);
    });
    // Set initial UI
    updateRatingUI(ratingTypeSelect.value);
  }

  function updateRatingUI(type) {
    // In gallery fullscreen, show/hide stars or yes/no
    const fsStars = document.getElementById('fs-stars');
    const fsYesNo = document.getElementById('fs-yesno');
    if (fsStars && fsYesNo) {
      if (type === 'star') {
        fsStars.style.display = 'block';
        fsYesNo.style.display = 'none';
      } else {
        fsStars.style.display = 'none';
        fsYesNo.style.display = 'block';
      }
    }
  }
  const upForm = document.getElementById('upload-form');
  if (upForm) {
    upForm.addEventListener('submit', handleUpload);
    document.getElementById('refresh-stats')?.addEventListener('click', loadStats);
    document.getElementById('load-top')?.addEventListener('click', loadTop);
    loadStats();

    // load sets for admin
    async function loadSets() {
      const sel = document.getElementById('set-select');
      if (!sel) return;
      sel.innerHTML = '';
      try {
        const data = await fetchJSON('/api/sets');
        for (const s of data.sets) {
          const opt = document.createElement('option');
          opt.value = s.slug;
          opt.textContent = `${s.name} (${s.image_count || 0})`;
          opt.dataset.slug = s.slug;
          opt.dataset.id = s.id;
          opt.dataset.count = s.image_count || 0;
          sel.appendChild(opt);
        }
        // ensure default selected
        if (!sel.value && sel.options.length) sel.value = sel.options[0].value;
        // update UI controls based on selected option (disable rename/delete for default)
        function updateSetControls() {
          const opt = sel.selectedOptions[0];
          const renameBtn = document.getElementById('rename-set');
          const deleteBtn = document.getElementById('delete-set');
          const uploadField = document.getElementById('upload-set-field');
          // allow renaming default, but do not allow deleting it
          const isDefault = opt && opt.dataset && opt.dataset.slug === 'default';
          if (renameBtn) renameBtn.disabled = false;
          if (deleteBtn) deleteBtn.disabled = isDefault;
          if (uploadField && opt) uploadField.value = opt.dataset.slug || '';
        }
        sel.addEventListener('change', updateSetControls);
        updateSetControls();
      } catch (e) {
        console.error('Failed to load sets', e);
      }
    }

    document.getElementById('create-set')?.addEventListener('click', async () => {
      const nameInput = document.getElementById('new-set-name');
      const name = nameInput?.value?.trim();
      if (!name) return alert('Enter a set name');
      try {
        const res = await postJSON('/api/sets', { name });
        await loadSets();
        // select new set
        const sel = document.getElementById('set-select');
        if (sel) sel.value = res.slug;
        nameInput.value = '';
      } catch (e) {
        alert('Failed to create set: ' + e.message);
      }
    });

    // initial sets
    loadSets();
    // populate stats set selector too
    async function loadStatsSets() {
      const sel = document.getElementById('stats-set-select');
      if (!sel) return;
      sel.innerHTML = '';
      try {
        const data = await fetchJSON('/api/sets');
        for (const s of data.sets) {
          const opt = document.createElement('option');
          opt.value = s.slug;
          opt.textContent = `${s.name} (${s.image_count || 0})`;
          sel.appendChild(opt);
        }
        if (!sel.value && sel.options.length) sel.value = sel.options[0].value;
      } catch (e) {
        console.error('Failed to load stats sets', e);
      }
    }
    loadStatsSets();
  document.getElementById('filter-set')?.addEventListener('click', () => { 
    // when user clicks Show Set, reload stats for the selected set
    loadStats();
    const statsSel = document.getElementById('stats-set-select');
    const tbody = document.querySelector('#stats-table tbody');
    if (tbody) tbody.dataset.currentSet = statsSel?.value || '';
  });
    // rename/delete handlers
    document.getElementById('rename-set')?.addEventListener('click', async () => {
      const sel = document.getElementById('set-select');
      const input = document.getElementById('new-set-name');
      if (!sel || !sel.value) return alert('Select a set');
      const selectedOpt = sel.selectedOptions[0];
      if (selectedOpt && selectedOpt.dataset && selectedOpt.dataset.slug === 'default') return alert('Cannot rename the default set');
      // prefer inline input; if empty, prompt the user
      let name = input?.value?.trim();
      if (!name) {
        name = prompt('Enter a new name for the selected set:','');
        if (!name) {
          // focus the inline input so the user can type
          input?.focus();
          return;
        }
        input.value = name;
      }
      try {
        // need set id: fetch sets list and find matching slug
        const data = await fetchJSON('/api/sets');
        const s = data.sets.find(x => x.slug === sel.value);
        if (!s) return alert('Set not found');
        const res = await postJSON('/api/sets/' + s.id + '/rename', { name });
        await loadSets();
        // select new slug
        sel.value = res.slug;
        input.value = '';
      } catch (e) {
        alert('Rename failed: ' + e.message);
      }
    });
    document.getElementById('delete-set')?.addEventListener('click', async () => {
      const sel = document.getElementById('set-select');
      if (!sel || !sel.value) return alert('Select a set');
      const selectedOpt = sel.selectedOptions[0];
      if (selectedOpt && selectedOpt.dataset && selectedOpt.dataset.slug === 'default') return alert('Cannot delete the default set');
      // determine count for selected option
      const count = selectedOpt?.dataset?.count || 0;
      if (!confirm(`Delete this set and its ${count} images? This cannot be undone.`)) return;
      try {
        const s = { id: opt.dataset.id, slug: opt.dataset.slug };
        const res = await postJSON('/api/sets/' + s.id + '/delete', {});
        await loadSets();
        loadStats();
      } catch (e) {
        alert('Delete failed: ' + e.message);
      }
    });

    document.getElementById('normalize-default')?.addEventListener('click', async () => {
      if (!confirm('Move bare files into uploads/default/ and update DB? This will move files on disk.')) return;
      try {
        const res = await postJSON('/api/migrate/normalize_default', {});
        alert(`Moved ${res.moved.length} files, updated ${res.updated_ids.length} DB rows, missing: ${res.missing.length}`);
        await loadSets();
        loadStats();
      } catch (e) {
        alert('Normalization failed: ' + e.message);
      }
    });

    // Remove all votes
    document.getElementById('remove-votes')?.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to remove ALL votes? This cannot be undone.')) return;
      try {
        await fetch('/api/remove_votes', { method: 'POST' });
        alert('All votes removed.');
        loadStats();
      } catch (e) {
        alert('Failed to remove votes.');
      }
    });

    // Delete all data
    document.getElementById('delete-all-data')?.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to DELETE ALL DATA (images and votes)? This cannot be undone.')) return;
      try {
        await fetch('/api/delete_all_data', { method: 'POST' });
        alert('All data deleted.');
        loadStats();
      } catch (e) {
        alert('Failed to delete all data.');
      }
    });

    // Download votes as JSON
    document.getElementById('download-votes')?.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/download_votes');
        if (!res.ok) throw new Error('Failed to download votes');
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'votes.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (e) {
        alert('Failed to download votes.');
      }
    });

    // Hide/unhide photo
    document.querySelector('#stats-table').addEventListener('click', async (ev) => {
      if (ev.target.classList.contains('hide-photo')) {
        const id = ev.target.dataset.id;
        const hide = ev.target.textContent === 'Hide' ? 1 : 0;
        await fetch('/api/hide_photo', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ image_id: id, hide })
        });
        loadStats();
      }
      if (ev.target.classList.contains('delete-photo')) {
        const id = ev.target.dataset.id;
        if (!confirm('Delete this photo and all its votes?')) return;
        await fetch('/api/delete_photo', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ image_id: id })
        });
        loadStats();
      }
    });
  }

  const gallery = document.getElementById('gallery');
  if (gallery) {
    document.getElementById('save-name').addEventListener('click', async () => {
      const v = document.getElementById('rater-name').value.trim();
      if (!v) { alert('Please enter a name'); return; }
      setName(v);
      await populateUserDropdown();
      loadGallery();
    });
    document.getElementById('apply-filters').addEventListener('click', () => {
      loadGallery();
    });
    // preload name
    const nm = getName();
    if (nm) document.getElementById('rater-name').value = nm;
    loadGallery();

    // Fullscreen gallery logic
    // (fsIndex, fsImages) are now declared at top-level scope
    const fsBtn = document.getElementById('fullscreen-btn');
    const fsView = document.getElementById('fullscreen-view');
    const fsImg = document.getElementById('fs-img');
    const fsStars = document.getElementById('fs-stars');
    const fsRating = document.getElementById('fs-rating');
    const fsExit = document.getElementById('fs-exit');

// Ensure showFSImage is defined before loadGallery
let fsIndex = 0, fsImages = [];
function showFSImage(idx) {
  if (!fsImages.length) return;
  fsIndex = ((idx % fsImages.length) + fsImages.length) % fsImages.length;
  const img = fsImages[fsIndex];
  const fsImg = document.getElementById('fs-img');
  const fsStars = document.getElementById('fs-stars');
  const fsRating = document.getElementById('fs-rating');
  fsImg.style.display = 'block';
  fsImg.src = img.url;
  fsImg.alt = img.filename;
  fsStars.innerHTML = starHTML(5, img.user_rating || 0);
  // update filename caption and progress
  const fsFilename = document.getElementById('fs-filename');
  if (fsFilename) fsFilename.textContent = img.filename || '';
  const fsProgress = document.getElementById('fs-progress');
  if (fsProgress) fsProgress.textContent = `${fsIndex+1} / ${fsImages.length}`;
  fsRating.textContent = img.user_rating ? `Your rating: ${img.user_rating} ★` : 'No rating yet';
  // Show user name and progress
  document.getElementById('fs-user').textContent = `User: ${getName()}`;
  document.getElementById('fs-progress').textContent = `${fsIndex+1}/${fsImages.length} (${((fsIndex+1)/fsImages.length*100).toFixed(1)}%)`;
  // Show/hide Yes/No voting UI based on rating type
  const ratingType = localStorage.getItem('ratingType') || 'star';
  const fsYesNo = document.getElementById('fs-yesno');
  if (ratingType === 'yesno') {
    fsYesNo.style.display = 'block';
    fsYesNo.innerHTML = `<button id="fs-yes">Yes</button><button id="fs-no">No</button>`;
    setTimeout(() => {
      document.getElementById('fs-yes')?.addEventListener('click', () => rateFSYesNo('Yes'));
      document.getElementById('fs-no')?.addEventListener('click', () => rateFSYesNo('No'));
    }, 100);
    document.getElementById('fs-stars').style.display = 'none';
  } else {
    fsYesNo.style.display = 'none';
    document.getElementById('fs-stars').style.display = 'block';
  }
}

    async function rateFSImage(val) {
      const img = fsImages[fsIndex];
      const name = getName().trim();
      if (!name) { alert('Please enter your name and click Save.'); return; }
      try {
        await postJSON('/api/rate', { image_id: img.id, user: name, rating: val });
        img.user_rating = val;
        showFSImage(fsIndex);
        fsRating.textContent = `Your rating: ${val} ★ (Saved!)`;
      } catch (e) {
        fsRating.textContent = 'Rating failed.';
      }
    }
    async function rateFSYesNo(val) {
      const img = fsImages[fsIndex];
      const name = getName().trim();
      if (!name) { alert('Please enter your name and click Save.'); return; }
      try {
        await postJSON('/api/rate_yesno', { image_id: img.id, user: name, yesno: val });
        showFSImage(fsIndex);
        fsRating.textContent = `Your vote: ${val} (Saved!)`;
      } catch (e) {
        fsRating.textContent = 'Vote failed.';
      }
    }

    fsBtn.addEventListener('click', () => {
      // Gather images from gallery
      fsImages = Array.from(document.querySelectorAll('#gallery .card-img')).map(card => {
        const imgEl = card.querySelector('img');
        const id = card.querySelector('.stars').dataset.imageId;
        const userRating = card.querySelectorAll('.star.filled').length;
        return {
          url: imgEl.src,
          filename: imgEl.alt,
          id: parseInt(id, 10),
          user_rating: userRating
        };
      });
      if (!fsImages.length) return;
      fsView.style.display = 'flex';
      showFSImage(0);
      document.body.style.overflow = 'hidden';
      // Yes/No voting event listeners
      setTimeout(() => {
        document.getElementById('fs-yes')?.addEventListener('click', () => rateFSYesNo('Yes'));
        document.getElementById('fs-no')?.addEventListener('click', () => rateFSYesNo('No'));
      }, 100);
    });

    fsExit.addEventListener('click', () => {
      fsView.style.display = 'none';
      document.body.style.overflow = '';
      loadGallery(); // Refresh gallery ratings after exiting fullscreen
    });

    document.addEventListener('keydown', (ev) => {
      if (fsView.style.display !== 'flex') return;
      const ratingType = localStorage.getItem('ratingType') || 'star';
      if (ev.key === 'ArrowRight') {
        showFSImage(fsIndex + 1);
      } else if (ev.key === 'ArrowLeft') {
        showFSImage(fsIndex - 1);
      } else if (ratingType === 'star' && ['1','2','3','4','5'].includes(ev.key)) {
        rateFSImage(parseInt(ev.key, 10));
      } else if (ratingType === 'yesno' && (ev.key === 'ArrowUp' || ev.key === 'ArrowDown')) {
        rateFSYesNo(ev.key === 'ArrowUp' ? 'Yes' : 'No');
      } else if (ev.key === 'Escape') {
        fsView.style.display = 'none';
        document.body.style.overflow = '';
        loadGallery(); // Refresh gallery ratings after exiting fullscreen
      }
    });
    // Click stars in fullscreen
    fsStars.addEventListener('click', (ev) => {
      if (!ev.target.classList.contains('star')) return;
      const val = parseInt(ev.target.dataset.value, 10);
      rateFSImage(val);
    });
  }
});
