var currentCategory = '全部';
var currentProject = 'Laldia';
var groupsData = [];
var drawerGroupId = null;
var messagesCache = {};
var contactsCache = {};

var INTERNAL_CATS = ['内部沟通', '施工局合作', '设计院合作'];
var EXTERNAL_CATS = ['供应商咨询', '地基处理', '建筑MEP', '保险'];
var ORDERED_CATS = INTERNAL_CATS.concat(EXTERNAL_CATS);

document.addEventListener('DOMContentLoaded', function () {
  loadProjects();
  loadAll();
  document.getElementById('refresh-btn').addEventListener('click', onRefresh);
  document.getElementById('search-input').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') onSearch();
  });
  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
  document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);
  document.getElementById('sync-modal-close').addEventListener('click', closeSyncModal);
  document.getElementById('sync-modal-overlay').addEventListener('click', closeSyncModal);
  document.getElementById('search-panel-close').addEventListener('click', closeSearchPanel);
  document.getElementById('project-select').addEventListener('change', onProjectChange);

  setInterval(doAutoSync, 60000);
  initColumnResize();
});

function loadProjects() {
  fetch('/api/projects')
    .then(function (r) { return r.json(); })
    .then(function (projects) {
      var sel = document.getElementById('project-select');
      sel.innerHTML = '';
      projects.forEach(function (p) {
        var opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p;
        sel.appendChild(opt);
      });
      sel.value = currentProject;
    })
    .catch(function (e) { console.error(e); });
}

function onProjectChange() {
  currentProject = document.getElementById('project-select').value;
  loadAll();
}

function loadAll() {
  fetch('/api/categories?project=' + encodeURIComponent(currentProject))
    .then(function (r) { return r.json(); })
    .then(function (cats) { renderTabs(cats); })
    .catch(function (e) { console.error(e); });

  fetch('/api/groups?project=' + encodeURIComponent(currentProject))
    .then(function (r) { return r.json(); })
    .then(function (groups) {
      groupsData = groups;
      renderTable(groups);
      updateMeta(groups);
      loadAllLatestMessages(groups);
      loadAllContacts(groups);
    })
    .catch(function (e) { console.error(e); });
}

function updateMeta(groups) {
  var now = new Date();
  var meta = document.getElementById('meta-info');
  meta.textContent = '更新: ' + now.toLocaleString('zh-CN') + ' | ' + groups.length + ' 个群';
}

function renderTabs(categories) {
  var container = document.getElementById('category-tabs');
  container.innerHTML = '';

  var allTab = document.createElement('span');
  allTab.className = 'tab active';
  allTab.textContent = '全部';
  allTab.dataset.cat = '全部';
  allTab.addEventListener('click', function () { setActiveTab(allTab, '全部'); });
  container.appendChild(allTab);

  var sortedCats = [];
  ORDERED_CATS.forEach(function (oc) {
    if (categories.indexOf(oc) !== -1) sortedCats.push(oc);
  });
  categories.forEach(function (c) {
    if (sortedCats.indexOf(c) === -1) sortedCats.push(c);
  });

  var seenInternal = false;
  var seenExternal = false;

  sortedCats.forEach(function (cat) {
    var isInternal = INTERNAL_CATS.indexOf(cat) !== -1;
    var isExternal = EXTERNAL_CATS.indexOf(cat) !== -1;

    if (isInternal && !seenInternal) {
      seenInternal = true;
    } else if (isExternal && !seenExternal && seenInternal) {
      seenExternal = true;
      var divider = document.createElement('span');
      divider.className = 'tab-divider';
      container.appendChild(divider);
    }

    var tab = document.createElement('span');
    tab.className = 'tab';
    tab.textContent = cat;
    tab.dataset.cat = cat;
    tab.addEventListener('click', function () { setActiveTab(tab, cat); });
    container.appendChild(tab);
  });
}

function setActiveTab(tab, category) {
  document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
  tab.classList.add('active');
  currentCategory = category;
  filterTable();
}

function filterTable() {
  var filtered = currentCategory === '全部'
    ? groupsData
    : groupsData.filter(function (g) { return g.category === currentCategory; });
  renderTable(filtered);
  updateMeta(filtered);
  filtered.forEach(function (g) {
    if (messagesCache[g.id] !== undefined) {
      renderMessagesCell(g.id, messagesCache[g.id]);
    } else {
      loadAllLatestMessages([g]);
    }
    if (contactsCache[g.id] !== undefined) {
      renderContactsCell(g.id, contactsCache[g.id]);
    } else {
      loadAllContacts([g]);
    }
  });
}

function renderTable(groups) {
  var tbody = document.getElementById('groups-tbody');
  tbody.innerHTML = '';

  if (groups.length === 0) {
    var tr = document.createElement('tr');
    var td = document.createElement('td');
    td.colSpan = 8;
    td.className = 'empty-state';
    td.textContent = '暂无群组数据';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  groups.forEach(function (g, idx) {
    var tr = document.createElement('tr');
    tr.className = getActivityClass(g.last_active_date);
    tr.addEventListener('click', function (e) {
      if (e.target.closest('.group-name')) return;
      openDrawer(g.id, g.name);
    });

    tr.appendChild(makeTd(idx + 1));

    var tdName = document.createElement('td');
    var nameSpan = document.createElement('span');
    nameSpan.className = 'group-name';
    nameSpan.textContent = g.name;
    nameSpan.addEventListener('click', function () {
      openDrawer(g.id, g.name);
    });
    tdName.appendChild(nameSpan);
    tr.appendChild(tdName);

    var tdCat = document.createElement('td');
    tdCat.className = 'cat-cell';
    tdCat.textContent = g.category;
    if (g.sub_category) {
      var subSpan = document.createElement('span');
      subSpan.className = 'sub-category';
      subSpan.textContent = g.sub_category;
      tdCat.appendChild(subSpan);
    }
    tr.appendChild(tdCat);

    var tdDate = document.createElement('td');
    tdDate.className = 'date-cell';
    var dateFormatted = formatDate(g.last_active_date);
    var spaceIdx = dateFormatted.indexOf(' ');
    if (spaceIdx !== -1) {
      var dateLine = document.createElement('span');
      dateLine.textContent = dateFormatted.substring(0, spaceIdx);
      tdDate.appendChild(dateLine);
      var br = document.createElement('br');
      tdDate.appendChild(br);
      var timeLine = document.createElement('span');
      timeLine.className = 'date-time';
      timeLine.textContent = dateFormatted.substring(spaceIdx + 1);
      tdDate.appendChild(timeLine);
    } else {
      tdDate.textContent = dateFormatted;
    }
    tr.appendChild(tdDate);

    tr.appendChild(makeTd(g.message_count || g.total_messages || 0));
    tr.appendChild(makeTd(g.group_creator || '-'));

    var tdMsgs = document.createElement('td');
    tdMsgs.className = 'msg-preview';
    tdMsgs.id = 'msgs-' + g.id;
    tdMsgs.textContent = '加载中...';
    tdMsgs.addEventListener('click', function (e) {
      e.stopPropagation();
      openDrawer(g.id, g.name);
    });
    tr.appendChild(tdMsgs);

    var tdContacts = document.createElement('td');
    tdContacts.className = 'contact-cell';
    tdContacts.id = 'contacts-' + g.id;
    tr.appendChild(tdContacts);

    tbody.appendChild(tr);
  });
}

function makeTd(text) {
  var td = document.createElement('td');
  td.textContent = text;
  return td;
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  if (dateStr.indexOf(' ') !== -1) {
    var parts = dateStr.split(' ');
    var dp = parts[0].split('-');
    var tp = parts[1].substring(0, 5);
    if (dp.length >= 3) return dp[0] + '.' + dp[1] + '.' + dp[2] + ' ' + tp;
    return dateStr;
  }
  var parts = dateStr.split('-');
  if (parts.length < 3) return dateStr;
  var y = parseInt(parts[0], 10);
  var m = parts[1];
  var d = parts[2];
  var now = new Date();
  if (y === now.getFullYear()) {
    return m + '.' + d;
  }
  return String(y).slice(2) + '.' + m + '.' + d;
}

function loadAllLatestMessages(groups) {
  groups.forEach(function (g) {
    fetch('/api/groups/' + g.id + '/messages/latest?n=3')
      .then(function (r) { return r.json(); })
      .then(function (msgs) {
        messagesCache[g.id] = msgs;
        renderMessagesCell(g.id, msgs);
      })
      .catch(function (e) { console.error(e); });
  });
}

function renderMessagesCell(groupId, msgs) {
  var cell = document.getElementById('msgs-' + groupId);
  if (!cell) return;
  cell.innerHTML = '';

  if (!msgs || msgs.length === 0) {
    cell.innerHTML = '<span class="empty-cell">暂无消息</span>';
    return;
  }

  var ul = document.createElement('ul');
  ul.className = 'msg-preview-list';

  msgs.forEach(function (m) {
    var li = document.createElement('li');

    var timeSpan = document.createElement('span');
    timeSpan.className = 'msg-time';
    timeSpan.textContent = formatDate(m.msg_date) + ' ';
    li.appendChild(timeSpan);

    var senderSpan = document.createElement('span');
    senderSpan.className = 'msg-sender';
    senderSpan.textContent = m.sender + ': ';
    li.appendChild(senderSpan);

    var fileInfo = parseFileInfo(m);
    if (fileInfo) {
      var fileSpan = document.createElement('span');
      fileSpan.className = 'file-indicator';
      fileSpan.textContent = '[文件] ' + truncate(fileInfo.filename, 40);
      li.appendChild(fileSpan);
    } else {
      li.appendChild(document.createTextNode(truncate(m.content, 60)));
    }
    ul.appendChild(li);
  });
  cell.appendChild(ul);
}

function loadAllContacts(groups) {
  groups.forEach(function (g) {
    fetch('/api/groups/' + g.id + '/contacts')
      .then(function (r) { return r.json(); })
      .then(function (contacts) {
        contactsCache[g.id] = contacts;
        renderContactsCell(g.id, contacts);
      })
      .catch(function (e) { console.error(e); });
  });
}

function renderContactsCell(groupId, contacts) {
  var cell = document.getElementById('contacts-' + groupId);
  if (!cell) return;
  cell.innerHTML = '';

  if (!contacts || contacts.length === 0) {
    cell.innerHTML = '<span class="empty-cell"></span>';
    return;
  }

  contacts.forEach(function (c) {
    var div = document.createElement('div');
    div.className = 'contact-item';
    var parts = [];
    if (c.sender_name) parts.push(c.sender_name);
    if (c.email) parts.push(c.email);
    if (c.phone) parts.push(c.phone);
    div.textContent = parts.join(' / ');
    cell.appendChild(div);
  });
}

function openDrawer(groupId, groupName) {
  var drawer = document.getElementById('drawer');
  var overlay = document.getElementById('drawer-overlay');
  var title = document.getElementById('drawer-title');
  var body = document.getElementById('drawer-body');

  drawerGroupId = groupId;
  title.textContent = groupName;
  body.innerHTML = '<div class="empty-state">加载中...</div>';

  drawer.classList.add('open');
  overlay.classList.add('show');
  document.body.style.overflow = 'hidden';

  loadDrawerMessages(groupId, 0);
}

function loadDrawerMessages(groupId, offset) {
  fetch('/api/groups/' + groupId + '/messages?limit=50&offset=' + offset)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var body = document.getElementById('drawer-body');
      if (offset === 0) body.innerHTML = '';

      if (!data.messages || data.messages.length === 0) {
        if (offset === 0) {
          body.innerHTML = '<div class="empty-state">暂无消息</div>';
        }
        return;
      }

      data.messages.forEach(function (m) {
        var item = document.createElement('div');
        item.className = 'msg-item';

        var sender = document.createElement('div');
        sender.className = 'sender';
        sender.textContent = m.sender;
        item.appendChild(sender);

        var time = document.createElement('div');
        time.className = 'time';
        time.textContent = m.msg_time || '';
        item.appendChild(time);

        var content = document.createElement('div');
        content.className = 'content';
        var fileInfo = parseFileInfo(m);
        if (fileInfo) {
          var fileLink = document.createElement('span');
          fileLink.className = 'file-link';
          fileLink.textContent = '[文件] ' + fileInfo.filename;
          fileLink.addEventListener('click', function () {
            onFileClick(fileInfo.filename, fileInfo.msg_date);
          });
          content.appendChild(fileLink);
        } else {
          content.textContent = m.content;
        }
        item.appendChild(content);

        body.appendChild(item);
      });

      if (data.total > offset + data.messages.length) {
        var oldLoadMore = body.querySelector('.load-more');
        if (oldLoadMore) oldLoadMore.remove();

        var shown = offset + data.messages.length;
        var loadMore = document.createElement('div');
        loadMore.className = 'load-more';
        loadMore.textContent = '加载更多... (' + shown + ' / ' + data.total + ')';
        loadMore.addEventListener('click', function () {
          loadMore.textContent = '加载中...';
          loadDrawerMessages(groupId, shown);
        });
        body.appendChild(loadMore);
      }
    })
    .catch(function (e) {
      var body = document.getElementById('drawer-body');
      body.innerHTML = '<div class="empty-state">加载失败</div>';
      console.error(e);
    });
}

function closeDrawer() {
  var drawer = document.getElementById('drawer');
  var overlay = document.getElementById('drawer-overlay');
  drawer.classList.remove('open');
  overlay.classList.remove('show');
  document.body.style.overflow = '';
  drawerGroupId = null;

  setTimeout(function () {
    document.getElementById('drawer-body').innerHTML = '';
  }, 300);
}

function onRefresh() {
  var modal = document.getElementById('sync-modal');
  var overlay = document.getElementById('sync-modal-overlay');
  var progress = document.getElementById('sync-progress');
  var statusText = document.getElementById('sync-status-text');
  var closeBtn = document.getElementById('sync-modal-close');

  modal.classList.add('show');
  overlay.classList.add('show');
  closeBtn.style.display = 'none';
  progress.style.width = '20%';
  progress.style.background = '#c47e3b';
  statusText.textContent = '正在发现新群组...';

  fetch('/api/sync/discover', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (discData) {
      progress.style.width = '40%';
      if (discData.new_groups && discData.new_groups.length > 0) {
        statusText.textContent = '发现 ' + discData.new_groups.length + ' 个新群组，正在拉取消息...';
      } else {
        statusText.textContent = '正在调用 wx-cli 拉取最新消息...';
      }

      fetch('/api/sync/refresh', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          progress.style.width = '100%';
          if (data.error) {
            progress.style.background = '#b84c4c';
            statusText.textContent = data.error;
          } else {
            progress.style.background = '#4a7c59';
            var parts = ['同步完成: 拉取 ' + (data.messages_new || 0) + ' 条新消息'];
            if (data.new_groups_discovered && data.new_groups_discovered.length > 0) {
              parts.push('发现 ' + data.new_groups_discovered.length + ' 个新群');
            }
            parts.push((data.groups_updated || 0) + ' 个群已更新');
            statusText.textContent = parts.join(', ');
          }
          closeBtn.style.display = '';
        })
        .catch(function (e) {
          progress.style.width = '100%';
          progress.style.background = '#b84c4c';
          statusText.textContent = '请求失败: ' + e.message;
          closeBtn.style.display = '';
        });
    })
    .catch(function (e) {
      progress.style.width = '40%';
      fetch('/api/sync/refresh', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          progress.style.width = '100%';
          progress.style.background = data.error ? '#b84c4c' : '#4a7c59';
          statusText.textContent = data.error || ('同步完成: ' + (data.messages_new || 0) + ' 条新消息');
          closeBtn.style.display = '';
        })
        .catch(function (e2) {
          progress.style.width = '100%';
          progress.style.background = '#b84c4c';
          statusText.textContent = '请求失败: ' + e2.message;
          closeBtn.style.display = '';
        });
    });
}

function closeSyncModal() {
  var modal = document.getElementById('sync-modal');
  var overlay = document.getElementById('sync-modal-overlay');
  var progress = document.getElementById('sync-progress');
  modal.classList.remove('show');
  overlay.classList.remove('show');
  progress.style.width = '0%';
  progress.style.background = '#c47e3b';
  loadAll();
}

function onSearch() {
  var q = document.getElementById('search-input').value.trim();
  if (!q) return;

  var panel = document.getElementById('search-panel');
  var title = document.getElementById('search-panel-title');
  var body = document.getElementById('search-panel-body');

  panel.style.display = 'flex';
  title.textContent = '搜索: ' + q;
  body.innerHTML = '<div class="empty-state">搜索中...</div>';

  fetch('/api/search?q=' + encodeURIComponent(q))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      body.innerHTML = '';

      if (!data.results || data.results.length === 0) {
        body.innerHTML = '<div class="empty-state">未找到与 "' + q + '" 相关的消息</div>';
        return;
      }

      data.results.forEach(function (m) {
        var item = document.createElement('div');
        item.className = 'search-result-item';

        var groupEl = document.createElement('div');
        groupEl.className = 'result-group';
        groupEl.textContent = m.group_name;
        item.appendChild(groupEl);

        var senderEl = document.createElement('div');
        senderEl.className = 'result-sender';
        senderEl.textContent = m.sender + ' | ' + (m.msg_time || '');
        item.appendChild(senderEl);

        var contentEl = document.createElement('div');
        contentEl.className = 'result-content';
        var fileInfo = parseFileInfo(m);
        if (fileInfo) {
          var fileLink = document.createElement('span');
          fileLink.className = 'file-link';
          fileLink.textContent = '[文件] ' + fileInfo.filename;
          fileLink.addEventListener('click', function (e) {
            e.stopPropagation();
            onFileClick(fileInfo.filename, fileInfo.msg_date);
          });
          contentEl.appendChild(fileLink);
        } else {
          contentEl.textContent = truncate(m.content, 140);
        }
        item.appendChild(contentEl);

        item.addEventListener('click', function () {
          closeSearchPanel();
          openDrawer(m.group_id, m.group_name);
        });
        body.appendChild(item);
      });
    })
    .catch(function (e) {
      body.innerHTML = '<div class="empty-state">搜索失败</div>';
      console.error(e);
    });
}

function closeSearchPanel() {
  var panel = document.getElementById('search-panel');
  panel.style.display = 'none';
}

function getActivityClass(dateStr) {
  if (!dateStr) return '';
  var d = new Date(dateStr);
  if (isNaN(d.getTime())) return '';
  var diffDays = (new Date() - d) / (1000 * 60 * 60 * 24);
  if (diffDays <= 3) return 'row-recent';
  if (diffDays <= 7) return 'row-medium';
  return 'row-old';
}

function doAutoSync() {
  fetch('/api/sync/refresh', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) return;
      if (data.messages_new > 0) {
        refreshCurrentView();
      }
    })
    .catch(function () {});
}

function refreshCurrentView() {
  messagesCache = {};
  contactsCache = {};

  fetch('/api/groups?project=' + encodeURIComponent(currentProject))
    .then(function (r) { return r.json(); })
    .then(function (groups) {
      groupsData = groups;
      var filtered = currentCategory === '全部'
        ? groupsData
        : groupsData.filter(function (g) { return g.category === currentCategory; });
      renderTable(filtered);
      updateMeta(filtered);
      filtered.forEach(function (g) {
        loadAllLatestMessages([g]);
        loadAllContacts([g]);
      });
    })
    .catch(function (e) { console.error(e); });
}

function truncate(s, maxLen) {
  if (!s) return '';
  if (s.length <= maxLen) return s;
  return s.substring(0, maxLen) + '...';
}

function parseFileInfo(msg) {
  if (msg.msg_type && (msg.msg_type.indexOf('文件') !== -1 || msg.msg_type.indexOf('链接') !== -1)) {
    var match = msg.content.match(/^\[文件\]\s*(.+)/);
    if (match) {
      return { filename: match[1], msg_date: msg.msg_date };
    }
  }
  return null;
}

function onFileClick(filename, msgDate) {
  fetch('/api/files/open?msg_date=' + encodeURIComponent(msgDate) + '&filename=' + encodeURIComponent(filename), { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.ok && data.error) {
        alert('文件不存在: ' + filename);
      }
    })
    .catch(function () {
      alert('打开文件失败: ' + filename);
    });
}

function initColumnResize() {
  var table = document.getElementById('groups-table');
  if (!table) return;

  var cols = table.querySelector('colgroup');
  if (!cols) return;

  var ths = table.querySelectorAll('thead th');
  var colElems = cols.querySelectorAll('col');
  var savedWidths = {};
  try {
    savedWidths = JSON.parse(localStorage.getItem('tableColWidths') || '{}');
  } catch (e) {}

  // Restore saved widths
  Object.keys(savedWidths).forEach(function (idx) {
    if (colElems[idx]) {
      colElems[idx].style.width = savedWidths[idx];
    }
  });

  var handle = null;
  var startX = 0;
  var startW = 0;
  var activeCol = null;
  var activeHandle = null;

  ths.forEach(function (th, idx) {
    if (idx === ths.length - 1) return; // Skip last column
    var h = document.createElement('div');
    h.className = 'resize-handle';
    h.addEventListener('mousedown', function (e) {
      e.preventDefault();
      e.stopPropagation();
      handle = h;
      startX = e.clientX;
      activeCol = colElems[idx];
      activeHandle = h;
      activeHandle.classList.add('active');
      startW = activeCol.getBoundingClientRect().width;
    });
    th.appendChild(h);
  });

  document.addEventListener('mousemove', function (e) {
    if (!handle) return;
    var diff = e.clientX - startX;
    var newW = Math.max(24, startW + diff);
    activeCol.style.width = newW + 'px';

    // Save widths
    var widths = {};
    colElems.forEach(function (col, i) {
      widths[i] = col.style.width || col.getBoundingClientRect().width + 'px';
    });
    try {
      localStorage.setItem('tableColWidths', JSON.stringify(widths));
    } catch (e) {}
  });

  document.addEventListener('mouseup', function () {
    if (activeHandle) activeHandle.classList.remove('active');
    handle = null;
    startX = 0;
    startW = 0;
    activeCol = null;
    activeHandle = null;
  });
}
