var currentCategory = '全部';
var currentCategoryFilter = '';
var currentCreatorFilter = '';
var currentProject = 'Laldia';
var groupsData = [];
var drawerGroupId = null;
var messagesCache = {};
var contactsCache = {};

var INTERNAL_CATS = ['内部沟通', '施工局合作', '设计院合作'];
var EXTERNAL_CATS = ['供应商咨询', '地基处理', '建筑MEP', '保险', '其他'];
var ORDERED_CATS = INTERNAL_CATS.concat(EXTERNAL_CATS);

document.addEventListener('DOMContentLoaded', function () {
  loadProjects();
  loadAll();
  document.getElementById('refresh-btn').addEventListener('click', onRefresh);
  document.getElementById('export-btn').addEventListener('click', onExport);
  document.getElementById('search-input').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') onSearch();
  });
  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
  document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);
  document.getElementById('search-panel-close').addEventListener('click', closeSearchPanel);
  document.getElementById('sidebar-projects').addEventListener('click', function (e) {
    var item = e.target.closest('.sidebar-project');
    if (!item) return;
    onProjectChange(item.dataset.project);
  });
  document.getElementById('bcc-mail-btn').addEventListener('click', handleBccMail);

  document.getElementById('category-filter').addEventListener('change', function () {
    currentCategoryFilter = this.value;
    filterTable();
  });

  document.getElementById('creator-filter').addEventListener('change', function () {
    currentCreatorFilter = this.value;
    filterTable();
  });

  document.getElementById('drawer-tabs').addEventListener('click', function(e) {
    var tab = e.target.closest('.drawer-tab');
    if (!tab) return;
    switchDrawerTab(tab.dataset.tab);
  });

  // 启动后自动同步一次，后续由用户手动刷新
  setTimeout(function () { onRefresh(); }, 500);
  initColumnResize();
});

function loadProjects() {
  fetch('/api/projects')
    .then(function (r) { return r.json(); })
    .then(function (projects) {
      var container = document.getElementById('sidebar-projects');
      container.innerHTML = '';
      projects.forEach(function (p) {
        var item = document.createElement('button');
        item.className = 'sidebar-project';
        if (p === currentProject) item.classList.add('active');
        item.dataset.project = p;

        var dot = document.createElement('span');
        dot.className = 'sidebar-project-dot';
        item.appendChild(dot);

        item.appendChild(document.createTextNode(p));
        container.appendChild(item);
      });
    })
    .catch(function (e) { console.error(e); });
}

function onProjectChange(projectName) {
  if (!projectName || projectName === currentProject) return;
  currentProject = projectName;
  var items = document.querySelectorAll('.sidebar-project');
  items.forEach(function (el) {
    el.classList.toggle('active', el.dataset.project === projectName);
  });
  loadAll();
}

function loadAll() {
  currentCategory = '全部';
  currentCategoryFilter = '';
  document.getElementById('category-filter').value = '';

  fetch('/api/categories?project=' + encodeURIComponent(currentProject))
    .then(function (r) { return r.json(); })
    .then(function (cats) { renderTabs(cats); })
    .catch(function (e) { console.error(e); });

  fetch('/api/groups?project=' + encodeURIComponent(currentProject) + '&with_details=1')
    .then(function (r) { return r.json(); })
    .then(function (groups) {
      groupsData = groups;
      groups.forEach(function (g) {
        messagesCache[g.id] = g.latest_messages || [];
        contactsCache[g.id] = g.contacts || [];
      });
      updateCreatorFilter(groups);
      updateCategoryFilterOptions();
      renderTable(groups);
      updateMeta(groups);
      groups.forEach(function (g) {
        renderMessagesCell(g.id, messagesCache[g.id]);
        renderContactsCell(g.id, contactsCache[g.id]);
      });
    })
    .catch(function (e) { console.error(e); });
}

function updateMeta(groups) {
  var now = new Date();
  var meta = document.getElementById('meta-info');
  meta.textContent = '更新: ' + now.toLocaleString('zh-CN') + ' | ' + groups.length + ' 个群';
}

function updateCreatorFilter(groups) {
  var sel = document.getElementById('creator-filter');
  var prevVal = sel.value;
  var creators = [];
  var seen = {};
  groups.forEach(function (g) {
    var c = g.group_creator;
    if (c && !seen[c]) {
      seen[c] = true;
      creators.push(c);
    }
  });
  creators.sort();
  sel.textContent = '';
  var defaultOpt = document.createElement('option');
  defaultOpt.value = '';
  defaultOpt.textContent = '按群主筛选';
  sel.appendChild(defaultOpt);
  creators.forEach(function (c) {
    var opt = document.createElement('option');
    opt.value = c;
    opt.textContent = c;
    sel.appendChild(opt);
  });
  if (creators.indexOf(prevVal) !== -1) {
    sel.value = prevVal;
  } else {
    sel.value = '';
    currentCreatorFilter = '';
  }
}

function updateCategoryFilterOptions() {
  var sel = document.getElementById('category-filter');
  var prevVal = sel.value;
  sel.textContent = '';

  if (currentCategory === '全部') {
    var defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = '按分类筛选';
    sel.appendChild(defaultOpt);
    ORDERED_CATS.forEach(function (c) {
      var opt = document.createElement('option');
      opt.value = c;
      opt.textContent = c;
      sel.appendChild(opt);
    });
  } else {
    var defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = '按子分类筛选';
    sel.appendChild(defaultOpt);
    var subCats = [];
    var seen = {};
    groupsData.forEach(function (g) {
      if (g.category === currentCategory && g.sub_category && !seen[g.sub_category]) {
        seen[g.sub_category] = true;
        subCats.push(g.sub_category);
      }
    });
    subCats.sort();
    subCats.forEach(function (sc) {
      var opt = document.createElement('option');
      opt.value = sc;
      opt.textContent = sc;
      sel.appendChild(opt);
    });
  }

  sel.value = prevVal;
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
    tab.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      tab.classList.add('drag-over');
    });
    tab.addEventListener('dragleave', function () {
      tab.classList.remove('drag-over');
    });
    tab.addEventListener('drop', function (e) {
      e.preventDefault();
      tab.classList.remove('drag-over');
      var groupId = parseInt(e.dataTransfer.getData('text/plain'), 10);
      var newCat = tab.dataset.cat;
      if (!groupId) return;
      fetch('/api/groups/' + groupId + '/category', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: newCat })
      })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          var group = groupsData.find(function (g) { return g.id === groupId; });
          if (group) group.category = newCat;
          filterTable();
          tab.style.transform = 'scale(1.1)';
          setTimeout(function () { tab.style.transform = ''; }, 200);
        }
      })
      .catch(function (e) { console.error(e); });
    });
    container.appendChild(tab);
  });
}

function setActiveTab(tab, category) {
  document.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('active'); });
  tab.classList.add('active');
  currentCategory = category;
  currentCategoryFilter = '';
  updateCategoryFilterOptions();
  document.getElementById('category-filter').value = '';
  filterTable();
}

function filterTable() {
  var filtered = groupsData;
  if (currentCategory !== '全部') {
    filtered = filtered.filter(function (g) { return g.category === currentCategory; });
  }
  if (currentCategoryFilter !== '') {
    if (currentCategory === '全部') {
      filtered = filtered.filter(function (g) { return g.category === currentCategoryFilter; });
    } else {
      filtered = filtered.filter(function (g) { return g.sub_category === currentCategoryFilter; });
    }
  }
  if (currentCreatorFilter !== '') {
    filtered = filtered.filter(function (g) { return g.group_creator === currentCreatorFilter; });
  }
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
    tr.draggable = true;
    tr.addEventListener('click', function (e) {
      if (e.target.closest('.group-name')) return;
      openDrawer(g.id, g.name);
    });
    tr.addEventListener('dragstart', function (e) {
      e.dataTransfer.setData('text/plain', g.id);
      e.dataTransfer.effectAllowed = 'move';
      tr.classList.add('dragging');
    });
    tr.addEventListener('dragend', function () {
      tr.classList.remove('dragging');
      document.querySelectorAll('.tab.drag-over').forEach(function (t) { t.classList.remove('drag-over'); });
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
    if (fileInfo && fileInfo.type === 'file') {
      var fileSpan = document.createElement('span');
      fileSpan.className = 'file-indicator';
      fileSpan.textContent = '[文件] ' + truncate(fileInfo.filename, 40);
      li.appendChild(fileSpan);
    } else if (fileInfo && fileInfo.type === 'image') {
      var imgSpan = document.createElement('span');
      imgSpan.className = 'file-indicator';
      imgSpan.textContent = '[图片]';
      imgSpan.style.cursor = 'pointer';
      imgSpan.addEventListener('click', function () {
        onImageClick(fileInfo.msg_date, fileInfo.timestamp);
      });
      li.appendChild(imgSpan);
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
    if (c.sender_name && c.display_name) {
      parts.push(c.sender_name + '（' + c.display_name + '）');
    } else if (c.sender_name) {
      parts.push(c.sender_name);
    }
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

  var tabs = document.querySelectorAll('#drawer-tabs .drawer-tab');
  tabs.forEach(function(t) { t.classList.remove('active'); });
  var msgTab = document.querySelector('#drawer-tabs .drawer-tab[data-tab="messages"]');
  if (msgTab) msgTab.classList.add('active');

  loadDrawerMessages(groupId, 0);
}

function switchDrawerTab(tabName) {
  var tabs = document.querySelectorAll('#drawer-tabs .drawer-tab');
  tabs.forEach(function(t) { t.classList.remove('active'); });
  var activeTab = document.querySelector('#drawer-tabs .drawer-tab[data-tab="' + tabName + '"]');
  if (activeTab) activeTab.classList.add('active');

  var body = document.getElementById('drawer-body');
  body.innerHTML = '<div class="empty-state">加载中...</div>';

  if (tabName === 'messages') {
    loadDrawerMessages(drawerGroupId, 0);
  } else if (tabName === 'summary') {
    loadDrawerSummaries(drawerGroupId);
  } else if (tabName === 'extractions') {
    loadDrawerExtractions(drawerGroupId);
  } else if (tabName === 'settings') {
    loadDrawerSettings(drawerGroupId);
  }
}

function loadDrawerSummaries(groupId) {
  fetch('/api/groups/' + groupId + '/summaries')
    .then(function(r) { return r.json(); })
    .then(function(summaries) {
      var body = document.getElementById('drawer-body');
      body.innerHTML = '';

      if (!summaries || summaries.length === 0) {
        body.innerHTML = '<div class="empty-state">暂无AI摘要</div>';
        return;
      }

      summaries.forEach(function(s) {
        var card = document.createElement('div');
        card.className = 'summary-card';

        if (s.date_range) {
          var range = document.createElement('div');
          range.className = 'summary-range';
          range.textContent = s.date_range;
          card.appendChild(range);
        }

        var text = document.createElement('div');
        text.className = 'summary-text';
        text.textContent = s.summary_text;
        card.appendChild(text);

        if (s.key_topics) {
          try {
            var topics = JSON.parse(s.key_topics);
            if (Array.isArray(topics) && topics.length > 0) {
              var tags = document.createElement('div');
              tags.className = 'summary-tags';
              topics.forEach(function(t) {
                var tag = document.createElement('span');
                tag.className = 'summary-tag';
                tag.textContent = t;
                tags.appendChild(tag);
              });
              card.appendChild(tags);
            }
          } catch(e) {}
        }

        body.appendChild(card);
      });
    })
    .catch(function(e) {
      document.getElementById('drawer-body').innerHTML = '<div class="empty-state">加载失败</div>';
      console.error(e);
    });
}

function loadDrawerExtractions(groupId) {
  fetch('/api/groups/' + groupId + '/extractions')
    .then(function(r) { return r.json(); })
    .then(function(extractions) {
      var body = document.getElementById('drawer-body');
      body.innerHTML = '';

      if (!extractions || extractions.length === 0) {
        body.innerHTML = '<div class="empty-state">暂无关键信息提取</div>';
        return;
      }

      var grouped = {};
      extractions.forEach(function(e) {
        if (!grouped[e.extract_type]) grouped[e.extract_type] = [];
        grouped[e.extract_type].push(e);
      });

      var typeOrder = ['联系人', '工期节点', '技术参数', '文件引用', '专业/供货类别'];
      var typeLabels = { '联系人': '联系人', '工期节点': '工期节点', '技术参数': '技术参数', '文件引用': '文件引用', '专业/供货类别': '专业/供货类别' };

      typeOrder.forEach(function(extType) {
        var items = grouped[extType];
        if (!items || items.length === 0) return;

        var section = document.createElement('div');
        section.className = 'extraction-section';

        var heading = document.createElement('div');
        heading.className = 'extraction-heading';
        heading.textContent = (typeLabels[extType] || extType) + ' (' + items.length + ')';
        section.appendChild(heading);

        items.forEach(function(item) {
          var row = document.createElement('div');
          row.className = 'extraction-row';
          try {
            var content = JSON.parse(item.content);
            if (extType === '联系人') {
              var displayName = content['姓名'] || '';
              if (content['微信名'] && content['真实称呼']) {
                displayName = content['微信名'] + '（' + content['真实称呼'] + '）';
              } else if (content['微信名']) {
                displayName = content['微信名'];
              }
              row.textContent = [displayName, content['角色'], content['邮箱']].filter(Boolean).join(' / ');
            } else if (extType === '工期节点') {
              row.textContent = [content['节点'], content['日期']].filter(Boolean).join(': ');
            } else if (extType === '技术参数') {
              row.textContent = [content['参数'], content['值']].filter(Boolean).join(': ');
            } else if (extType === '文件引用') {
              var filename = content['文件'];
              var msgDate = content['msg_date'] || content['日期'];
              if (filename) {
                var fileLink = document.createElement('span');
                fileLink.className = 'file-link';
                fileLink.textContent = '[文件] ' + filename;
                if (content['说明']) fileLink.textContent += ' (' + content['说明'] + ')';
                fileLink.addEventListener('click', function () {
                  onFileClick(filename, msgDate);
                });
                row.appendChild(fileLink);
              } else {
                row.textContent = JSON.stringify(content);
              }
            } else if (extType === '专业/供货类别') {
              row.textContent = [content['类别'], content['专业'], content['说明']].filter(Boolean).join(' / ');
            } else {
              row.textContent = JSON.stringify(content);
            }
          } catch(e) {
            row.textContent = item.content;
          }
          section.appendChild(row);
        });

        body.appendChild(section);
      });

      Object.keys(grouped).forEach(function(extType) {
        if (typeOrder.indexOf(extType) !== -1) return;
        var items = grouped[extType];
        var section = document.createElement('div');
        section.className = 'extraction-section';
        var heading = document.createElement('div');
        heading.className = 'extraction-heading';
        heading.textContent = extType + ' (' + items.length + ')';
        section.appendChild(heading);
        items.forEach(function(item) {
          var row = document.createElement('div');
          row.className = 'extraction-row';
          try {
            var content = JSON.parse(item.content);
            row.textContent = JSON.stringify(content);
          } catch(e) {
            row.textContent = item.content;
          }
          section.appendChild(row);
        });
        body.appendChild(section);
      });
    })
    .catch(function(e) {
      document.getElementById('drawer-body').innerHTML = '<div class="empty-state">加载失败</div>';
      console.error(e);
    });
}

function loadDrawerSettings(groupId) {
  fetch('/api/groups/' + groupId + '/settings')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var body = document.getElementById('drawer-body');
      body.innerHTML = '';

      var form = document.createElement('div');
      form.className = 'settings-form';

      var manualNote = document.createElement('div');
      manualNote.className = 'settings-note';
      if (data.manual_category) {
        manualNote.textContent = '此群的分类/项目已手动锁定，AI 自动分类将跳过此群。';
        manualNote.style.color = 'var(--green)';
      } else {
        manualNote.textContent = '修改后分类和项目将被锁定，AI 自动分类将跳过此群（摘要和提取不受影响）。';
      }
      form.appendChild(manualNote);

      function addRow(label, el) {
        var row = document.createElement('div');
        row.className = 'settings-row';
        var lbl = document.createElement('label');
        lbl.className = 'settings-label';
        lbl.textContent = label;
        row.appendChild(lbl);
        row.appendChild(el);
        form.appendChild(row);
      }

      var projectSelect = document.createElement('select');
      projectSelect.className = 'settings-input';
      data.projects.forEach(function(p) {
        var opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p;
        if (p === data.project) opt.selected = true;
        projectSelect.appendChild(opt);
      });
      addRow('项目', projectSelect);

      var catSelect = document.createElement('select');
      catSelect.className = 'settings-input';
      data.categories.forEach(function(c) {
        var opt = document.createElement('option');
        opt.value = c;
        opt.textContent = c;
        if (c === data.category) opt.selected = true;
        catSelect.appendChild(opt);
      });
      addRow('分类', catSelect);

      var subInput = document.createElement('input');
      subInput.type = 'text';
      subInput.className = 'settings-input';
      subInput.value = data.sub_category || '';
      subInput.placeholder = '例如: 钢结构、消防...';
      addRow('子分类', subInput);

      var btnRow = document.createElement('div');
      btnRow.className = 'settings-btn-row';

      var saveBtn = document.createElement('button');
      saveBtn.className = 'settings-save-btn';
      saveBtn.textContent = '保存设置';
      saveBtn.addEventListener('click', function() {
        saveBtn.textContent = '保存中...';
        saveBtn.disabled = true;
        fetch('/api/groups/' + groupId + '/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project: projectSelect.value,
            category: catSelect.value,
            sub_category: subInput.value.trim()
          })
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
          if (res.ok) {
            saveBtn.textContent = '已保存';
            saveBtn.style.background = 'var(--green)';
            setTimeout(function() { closeDrawer(); loadAll(); }, 600);
          } else {
            saveBtn.textContent = '保存失败, 重试';
            saveBtn.disabled = false;
          }
        })
        .catch(function() {
          saveBtn.textContent = '保存失败, 重试';
          saveBtn.disabled = false;
        });
      });
      btnRow.appendChild(saveBtn);

      var unlockBtn = document.createElement('button');
      unlockBtn.className = 'settings-unlock-btn';
      unlockBtn.textContent = '解除锁定';
      unlockBtn.title = '恢复AI自动分类';
      unlockBtn.addEventListener('click', function() {
        if (!confirm('确认解除锁定? AI将恢复对此群的自动分类和项目归属。')) return;
        unlockBtn.textContent = '处理中...';
        unlockBtn.disabled = true;
        fetch('/api/groups/' + groupId + '/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project: projectSelect.value,
            category: catSelect.value,
            sub_category: subInput.value.trim(),
            unlock: true
          })
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
          if (res.ok) {
            unlockBtn.textContent = '已解锁';
            setTimeout(function() { closeDrawer(); loadAll(); }, 600);
          }
        })
        .catch(function() {});
      });
      btnRow.appendChild(unlockBtn);
      form.appendChild(btnRow);

      body.appendChild(form);
    })
    .catch(function(e) {
      document.getElementById('drawer-body').innerHTML = '<div class="empty-state">加载失败</div>';
      console.error(e);
    });
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
        if (fileInfo && fileInfo.type === 'file') {
          var fileLink = document.createElement('span');
          fileLink.className = 'file-link';
          fileLink.textContent = '[文件] ' + fileInfo.filename;
          fileLink.addEventListener('click', function () {
            onFileClick(fileInfo.filename, fileInfo.msg_date);
          });
          content.appendChild(fileLink);
        } else if (fileInfo && fileInfo.type === 'image') {
          var imgWrapper = document.createElement('div');
          imgWrapper.className = 'inline-image-wrapper';
          var imgEl = document.createElement('img');
          imgEl.className = 'inline-image';
          var imgUrl = '/api/images/view?msg_date=' + encodeURIComponent(fileInfo.msg_date);
          if (fileInfo.timestamp) imgUrl += '&timestamp=' + encodeURIComponent(fileInfo.timestamp);
          if (fileInfo.local_id != null) imgUrl += '&local_id=' + encodeURIComponent(fileInfo.local_id);
          if (groupId != null) imgUrl += '&group_id=' + encodeURIComponent(groupId);
          imgEl.src = imgUrl;
          imgEl.alt = '[图片]';
          imgEl.loading = 'lazy';
          imgEl.style.cursor = 'pointer';
          imgEl.addEventListener('error', function () {
            while (imgWrapper.firstChild) imgWrapper.removeChild(imgWrapper.firstChild);
            var fallback = document.createElement('span');
            fallback.className = 'file-link';
            fallback.textContent = '[图片 — 解密失败，请先在微信中查看该图片后重试]';
            imgWrapper.appendChild(fallback);
          });
          imgEl.addEventListener('click', function () {
            window.open(imgUrl, '_blank');
          });
          imgWrapper.appendChild(imgEl);
          content.appendChild(imgWrapper);
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

function onExport() {
  var qs = 'project=' + encodeURIComponent(currentProject);
  if (currentCategory && currentCategory !== '全部') {
    qs += '&category=' + encodeURIComponent(currentCategory);
  }
  if (currentCreatorFilter !== '') {
    qs += '&group_creator=' + encodeURIComponent(currentCreatorFilter);
  }
  fetch('/api/export/excel?' + qs)
    .then(function(resp) {
      if (!resp.ok) throw new Error('导出失败 (' + resp.status + ')');
      return resp.blob();
    })
    .then(function(blob) {
      var today = new Date().toISOString().slice(0,10).replace(/-/g,'');
      var cat = (currentCategory && currentCategory !== '全部') ? currentCategory : '全部';
      var filename = 'WXGLedger_' + currentProject + '_' + cat + '_' + today + '.xlsx';
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    })
    .catch(function(err) {
      alert('导出失败: ' + err.message);
    });
}

var _syncPollTimer = null;
var _syncDoneTimer = null;

function showSyncPanel() {
  document.getElementById('sync-overlay').classList.add('show');
  var panel = document.getElementById('sync-panel');
  panel.classList.add('show');
  var doneEl = panel.querySelector('.sync-done');
  if (doneEl) doneEl.remove();
  var warnEl = panel.querySelector('.sync-daemon-warn');
  if (warnEl) warnEl.remove();
  document.getElementById('sync-phase-text').textContent = '准备同步...';
  document.getElementById('sync-counter').textContent = '';
  document.getElementById('sync-progress-fill').style.width = '0%';
  document.getElementById('sync-current').textContent = '';
  document.getElementById('sync-elapsed').textContent = '';
  clearSyncLog();
  hideSyncErrors();
}

function clearSyncLog() {
  var log = document.getElementById('sync-log');
  while (log.firstChild) log.removeChild(log.firstChild);
}

function appendSyncLogLine(text) {
  var log = document.getElementById('sync-log');
  var div = document.createElement('div');
  div.className = 'log-line';
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function hideSyncErrors() {
  var err = document.getElementById('sync-errors');
  err.style.display = 'none';
  while (err.firstChild) err.removeChild(err.firstChild);
}

function showSyncError(text) {
  var err = document.getElementById('sync-errors');
  err.style.display = 'block';
  var div = document.createElement('div');
  div.className = 'err-line';
  div.textContent = text;
  err.appendChild(div);
}

function updateSyncPanel(data) {
  var phaseMap = {
    'starting': '正在启动...',
    'discovering': '正在扫描新群...',
    'syncing_new': '正在同步新群...',
    'analyzing': '正在分析群组活跃状态...',
    'syncing': '正在同步消息...',
    'writing': '正在写入数据库...',
    'files': '正在检查文件...',
    'done': '同步完成'
  };
  document.getElementById('sync-phase-text').textContent = phaseMap[data.phase] || data.phase;

  // Show elapsed time
  if (data.elapsed > 0 && data.phase !== 'done') {
    document.getElementById('sync-elapsed').textContent = '已耗时 ' + Math.round(data.elapsed) + ' 秒';
  } else if (data.phase === 'done') {
    document.getElementById('sync-elapsed').textContent = '耗时 ' + Math.round(data.elapsed) + ' 秒';
  }

  // Daemon startup warning
  var panel = document.getElementById('sync-panel');
  var warnEl = panel.querySelector('.sync-daemon-warn');
  if (data.phase === 'starting') {
    if (!warnEl) {
      warnEl = document.createElement('div');
      warnEl.className = 'sync-daemon-warn';
      warnEl.textContent = '正在启动微信数据连接（提取密钥+解密数据库），约需 15-20 秒，请勿重复点击刷新！';
      panel.insertBefore(warnEl, document.getElementById('sync-log'));
    }
  } else {
    if (warnEl) warnEl.remove();
  }

  if (data.total_groups > 0 && (data.phase === 'syncing' || data.phase === 'syncing_new')) {
    document.getElementById('sync-counter').textContent = data.group_index + '/' + data.total_groups;
    var pct = Math.round((data.group_index / data.total_groups) * 100);
    document.getElementById('sync-progress-fill').style.width = pct + '%';
  } else if (data.phase === 'done') {
    document.getElementById('sync-progress-fill').style.width = '100%';
    document.getElementById('sync-counter').textContent = '';
  } else if (data.phase === 'starting') {
    // Simulate progress based on elapsed time (daemon takes ~18s)
    var pct = Math.min(Math.round((data.elapsed / 20) * 30), 30);
    document.getElementById('sync-progress-fill').style.width = pct + '%';
    document.getElementById('sync-counter').textContent = '';
  } else {
    document.getElementById('sync-progress-fill').style.width = '10%';
    document.getElementById('sync-counter').textContent = '';
  }

  if (data.current_group) {
    document.getElementById('sync-current').textContent = data.current_group;
  }

  if (data.log_lines && data.log_lines.length > 0) {
    clearSyncLog();
    data.log_lines.forEach(function (line) { appendSyncLogLine(line); });
  }

  if (data.errors && data.errors.length > 0) {
    hideSyncErrors();
    data.errors.forEach(function (e) { showSyncError(e); });
  }
}

function closeSyncPanel(delay) {
  delay = delay || 0;
  if (_syncDoneTimer) clearTimeout(_syncDoneTimer);
  _syncDoneTimer = setTimeout(function () {
    document.getElementById('sync-overlay').classList.remove('show');
    document.getElementById('sync-panel').classList.remove('show');
    if (_syncPollTimer) { clearTimeout(_syncPollTimer); _syncPollTimer = null; }
  }, delay);
}

function showSyncDone(result) {
  var panel = document.getElementById('sync-panel');
  var oldDone = panel.querySelector('.sync-done');
  if (oldDone) oldDone.remove();

  var doneEl = document.createElement('div');
  doneEl.className = 'sync-done';

  var textEl = document.createElement('div');
  textEl.className = 'sync-done-text';
  var newGroups = (result.new_groups_discovered || []).length;
  var newMsgs = result.messages_new || 0;
  var parts = [];
  if (newMsgs > 0) parts.push('+' + newMsgs + ' 条新消息');
  if (newGroups > 0) parts.push('+' + newGroups + ' 个新群');
  if (result.groups_updated > 0) parts.push(result.groups_updated + ' 个群有更新');
  if (parts.length === 0) parts.push('无新增内容');
  textEl.textContent = parts.join(' · ');
  doneEl.appendChild(textEl);

  var closeBtn = document.createElement('button');
  closeBtn.className = 'sync-done-close';
  closeBtn.textContent = '关闭';
  closeBtn.addEventListener('click', function () { closeSyncPanel(0); });
  doneEl.appendChild(closeBtn);

  panel.appendChild(doneEl);
  if (_syncDoneTimer) clearTimeout(_syncDoneTimer);
  _syncDoneTimer = setTimeout(function () { closeSyncPanel(0); }, 4000);
}

function onRefresh() {
  var btn = document.getElementById('refresh-btn');
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('syncing');

  showSyncPanel();

  fetch('/api/sync/refresh', { method: 'POST', headers: { 'X-Sync-Token': 'wxdashboard-sync' } })
    .then(function (r) { return r.json(); })
    .then(function () {
      function poll() {
        fetch('/api/sync/refresh/status')
          .then(function (r) { return r.json(); })
          .then(function (s) {
            if (!s.running) {
              btn.disabled = false;
              btn.classList.remove('syncing');
              var result = s.result || {};

              if (result.status === 'daemon_unavailable') {
                updateSyncPanel({ phase: 'done', log_lines: [], errors: ['微信未运行，无法同步。请确认微信已打开。'] });
                showSyncDone({ messages_new: 0, new_groups_discovered: [], groups_updated: 0 });
                return;
              }
              if (result.error) {
                updateSyncPanel({ phase: 'done', log_lines: [], errors: [result.error] });
                showSyncDone({ messages_new: 0, new_groups_discovered: [], groups_updated: 0 });
                return;
              }

              updateSyncPanel({ phase: 'done', log_lines: s.log_lines || [], errors: s.errors || [], total_groups: s.total_groups || 0, group_index: s.total_groups || 0 });
              showSyncDone(result);
              refreshCurrentView();
            } else {
              updateSyncPanel(s);
              _syncPollTimer = setTimeout(poll, 400);
            }
          });
      }
      _syncPollTimer = setTimeout(poll, 300);
    })
    .catch(function () {
      btn.disabled = false;
      btn.classList.remove('syncing');
      updateSyncPanel({ phase: 'done', log_lines: [], errors: ['同步请求失败，请稍后重试'] });
      showSyncDone({ messages_new: 0, new_groups_discovered: [], groups_updated: 0 });
    });
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
        if (fileInfo && fileInfo.type === 'file') {
          var fileLink = document.createElement('span');
          fileLink.className = 'file-link';
          fileLink.textContent = '[文件] ' + fileInfo.filename;
          fileLink.addEventListener('click', function (e) {
            e.stopPropagation();
            onFileClick(fileInfo.filename, fileInfo.msg_date);
          });
          contentEl.appendChild(fileLink);
        } else if (fileInfo && fileInfo.type === 'image') {
          var imgLink = document.createElement('span');
          imgLink.className = 'file-link';
          imgLink.textContent = '[图片]';
          imgLink.addEventListener('click', function (e) {
            e.stopPropagation();
            onImageClick(fileInfo.msg_date, fileInfo.timestamp);
          });
          contentEl.appendChild(imgLink);
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

function refreshCurrentView(onComplete) {
  messagesCache = {};
  contactsCache = {};

  fetch('/api/groups?project=' + encodeURIComponent(currentProject) + '&with_details=1')
    .then(function (r) { return r.json(); })
    .then(function (groups) {
      groupsData = groups;
      groups.forEach(function (g) {
        messagesCache[g.id] = g.latest_messages || [];
        contactsCache[g.id] = g.contacts || [];
      });
      updateCreatorFilter(groups);
      var filtered = groupsData;
      if (currentCategory !== '全部') {
        filtered = filtered.filter(function (g) { return g.category === currentCategory; });
      }
      if (currentCategoryFilter !== '') {
        if (currentCategory === '全部') {
          filtered = filtered.filter(function (g) { return g.category === currentCategoryFilter; });
        } else {
          filtered = filtered.filter(function (g) { return g.sub_category === currentCategoryFilter; });
        }
      }
      if (currentCreatorFilter !== '') {
        filtered = filtered.filter(function (g) { return g.group_creator === currentCreatorFilter; });
      }
      renderTable(filtered);
      updateMeta(filtered);
      filtered.forEach(function (g) {
        renderMessagesCell(g.id, messagesCache[g.id]);
        renderContactsCell(g.id, contactsCache[g.id]);
      });
      if (onComplete) onComplete();
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
      return { type: 'file', filename: match[1], msg_date: msg.msg_date };
    }
  }
  if (msg.msg_type && msg.msg_type.indexOf('图片') !== -1) {
    var ts = null;
    try {
      if (msg.raw_json) {
        var raw = JSON.parse(msg.raw_json);
        ts = raw.timestamp;
      }
    } catch(e) {}
    return { type: 'image', msg_date: msg.msg_date, timestamp: ts, local_id: msg.local_id };
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

function onImageClick(msgDate, timestamp) {
  var params = 'msg_date=' + encodeURIComponent(msgDate);
  if (timestamp) params += '&timestamp=' + encodeURIComponent(timestamp);
  fetch('/api/images/open?' + params, { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.ok && data.error) {
        alert('无法打开图片: ' + data.error);
      }
    })
    .catch(function () {
      alert('打开图片失败');
    });
}

function handleBccMail() {
  var category = currentCategory;
  if (category === '全部') {
    alert('请先选择左侧分类，再对该分类下所有联系人群发邮件');
    return;
  }
  var project = currentProject;
  var btn = document.getElementById('bcc-mail-btn');
  btn.disabled = true;

  fetch('/api/contacts/bcc?category=' + encodeURIComponent(category) + '&project=' + encodeURIComponent(project))
    .then(function (r) { return r.json(); })
    .then(function (contacts) {
      btn.disabled = false;
      if (!contacts || contacts.length === 0) {
        alert('分类 "' + category + '" 下没有可用的联系人邮箱');
        return;
      }
      var bcc = contacts.map(function (c) {
        if (c.name) { return c.name + ' <' + c.email + '>'; }
        return c.email;
      }).join(';');
      var mailto = 'mailto:?bcc=' + encodeURIComponent(bcc);
      window.open(mailto, '_blank');
    })
    .catch(function () {
      btn.disabled = false;
      alert('获取联系人邮箱失败');
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
