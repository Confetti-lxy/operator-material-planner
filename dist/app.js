const featuredMeta = {
  "能天使": { profession: "狙击 · 速射手", tone: "#d39038" },
  "桃金娘": { profession: "先锋 · 执旗手", tone: "#cf765f" },
  "阿米娅": { profession: "术师 · 中坚术师", tone: "#556b78" },
  "史尔特尔": { profession: "近卫 · 术战者", tone: "#b34e3e" },
  "塞雷娅": { profession: "重装 · 守护者", tone: "#687167" },
  "澄闪": { profession: "术师 · 驭械术师", tone: "#b99b55" }
};
const palette = ["#ad6f40", "#6d7f67", "#657a91", "#97745f", "#7b6d91", "#8c7447", "#637f80", "#89656b"];
const state = { active: "能天使", selected: new Set(), modes: {}, summaryMode: 'original' };
let operators = {}, recipes = {}, metadata = {}, operatorOrder = [];

function hashName(name) {
  return [...name].reduce((value, char) => ((value * 31) + char.codePointAt(0)) >>> 0, 7);
}

function operatorMeta(name, op) {
  const data = metadata[name];
  if (data) return {
    ...data,
    professionLabel: [data.profession, data.branch].filter(Boolean).join(' · '),
    tone: palette[hashName(name) % palette.length]
  };
  if (featuredMeta[name]) return {...featuredMeta[name], professionLabel: featuredMeta[name].profession};
  return {
    profession: '干员', professionLabel: `${op.rarity}★ 干员`,
    tone: palette[hashName(name) % palette.length]
  };
}

async function init() {
  const [opData, recipeData, metadataData] = await Promise.all([
    fetch('./data/operator_material_requirements.json').then(r => r.json()),
    fetch('./data/material_recipes.json').then(r => r.json()),
    fetch('./data/operator_metadata.json').then(r => r.json())
  ]);
  operators = opData.operators;
  recipes = recipeData.materials;
  operatorOrder = metadataData.operators.map(item => item.name).filter(name => operators[name]);
  metadata = Object.fromEntries(metadataData.operators.map(item => [item.name, item]));
  document.querySelector('#operatorCount').textContent = Object.keys(operators).length;
  populateFilters(); renderOperatorList(); renderDetail(); bindGlobal();
}

function bindGlobal() {
  document.querySelector('#searchInput').addEventListener('input', renderOperatorList);
  document.querySelector('#professionFilter').addEventListener('change', event => {
    updateBranchFilter(event.target.value);
    renderOperatorList();
  });
  ['rarityFilter','branchFilter','factionFilter'].forEach(id => document.querySelector(`#${id}`).addEventListener('change', renderOperatorList));
  document.querySelector('#resetFilters').addEventListener('click', () => {
    document.querySelector('#searchInput').value = '';
    ['professionFilter','rarityFilter','factionFilter'].forEach(id => document.querySelector(`#${id}`).value = '');
    updateBranchFilter('');
    renderOperatorList();
  });
  document.querySelectorAll('[data-global-mode]').forEach(btn => btn.addEventListener('click', () => {
    groupsFor(operators[state.active]).forEach(g => g.stages.forEach(s => state.modes[s.id] = btn.dataset.globalMode));
    renderRequirements(); renderSummary();
  }));
  document.querySelector('#clearAll').addEventListener('click', () => { state.selected.clear(); renderRequirements(); renderSummary(); });
  document.querySelectorAll('[data-summary-mode]').forEach(btn => btn.addEventListener('click', () => {
    state.summaryMode = btn.dataset.summaryMode;
    renderSummary();
  }));
  document.querySelector('#themeToggle').addEventListener('click', () => document.body.classList.toggle('dark'));
}

function populateFilters() {
  const rows = Object.values(metadata);
  const fill = (id, values, suffix='') => {
    const select = document.querySelector(`#${id}`);
    select.insertAdjacentHTML('beforeend', values.map(value => `<option value="${value}">${value}${suffix}</option>`).join(''));
  };
  const professionOrder = ['先锋','近卫','重装','狙击','术师','医疗','辅助','特种'];
  fill('professionFilter', professionOrder.filter(value => rows.some(row => row.profession === value)));
  fill('rarityFilter', [6,5,4,3,2,1].filter(value => rows.some(row => row.rarity === value)), '★');
  updateBranchFilter('');
  fill('factionFilter', [...new Set(rows.flatMap(row => row.factions || []))].sort((a,b) => a.localeCompare(b,'zh-CN')));
}

function updateBranchFilter(profession) {
  const select = document.querySelector('#branchFilter');
  const previous = select.value;
  const branches = [...new Set(Object.values(metadata)
    .filter(row => !profession || row.profession === profession)
    .map(row => row.branch)
    .filter(Boolean))]
    .sort((a,b) => a.localeCompare(b,'zh-CN'));
  select.innerHTML = `<option value="">${profession ? `全部${profession}分支` : '全部分支'}</option>` + branches.map(branch => `<option value="${branch}">${branch}</option>`).join('');
  select.value = branches.includes(previous) ? previous : '';
}

function renderOperatorList() {
  const q = (document.querySelector('#searchInput')?.value?.trim() || '').toLocaleLowerCase();
  const profession = document.querySelector('#professionFilter')?.value || '';
  const rarity = Number(document.querySelector('#rarityFilter')?.value || 0);
  const branch = document.querySelector('#branchFilter')?.value || '';
  const faction = document.querySelector('#factionFilter')?.value || '';
  const names = operatorOrder.filter(name => {
    const meta = metadata[name];
    const searchable = `${name} ${meta?.appellation || ''}`.toLocaleLowerCase();
    return (!q || searchable.includes(q)) && (!profession || meta?.profession === profession) && (!rarity || meta?.rarity === rarity) && (!branch || meta?.branch === branch) && (!faction || meta?.factions?.includes(faction));
  });
  document.querySelector('#resultCount').textContent = names.length;
  document.querySelector('#operatorList').innerHTML = names.map(name => {
    const op = operators[name], meta = operatorMeta(name, op);
    return `<button class="operator-row ${name===state.active?'active':''}" data-name="${name}">
      <span class="mini-portrait" style="background:linear-gradient(145deg,${meta.tone},#242422)"><img src="./assets/operators/${meta.id}.webp" alt="" loading="lazy"></span>
      <span><strong>${name}</strong><small>${meta.profession}</small></span>
      <span class="stars">${'★'.repeat(op.rarity)}</span>
    </button>`;
  }).join('') || '<div class="empty-state">没有匹配的干员</div>';
  document.querySelectorAll('.operator-row').forEach(btn => btn.onclick = () => {
    state.active = btn.dataset.name; state.selected.clear(); state.modes = {}; renderOperatorList(); renderDetail();
  });
}

function renderDetail() {
  const op = operators[state.active]; if (!op) return;
  const meta = operatorMeta(state.active, op);
  document.querySelector('#operatorName').textContent = state.active;
  document.querySelector('#rarityBadge').textContent = `${op.rarity}★`;
  document.querySelector('#professionBadge').textContent = meta.professionLabel;
  const portrait = document.querySelector('#portrait'); portrait.innerHTML = `<img src="./assets/operators/${meta.id}.webp" alt="${state.active}">`; portrait.style.background = `linear-gradient(145deg,${meta.tone},#242422)`;
  syncMasterControls();
  renderRequirements(); renderSummary();
}

function groupsFor(op) {
  const groups=[];
  if (Object.keys(op.elite_materials).length) groups.push({ id:'elite', title:'精英化', sub:'Elite promotion', stages:Object.entries(op.elite_materials).map(([k,v])=>({ id:`elite-${k}`, label:k==='0_to_1'?'精英 0 → 1':'精英 1 → 2', mats:v })) });
  Object.entries(op.mastery_materials).forEach(([skill,ranks],i)=> groups.push({ id:`skill-${i}`, title:skill, sub:`技能 ${i+1} · 专精训练`, stages:Object.entries(ranks).map(([k,v])=>({ id:`skill-${i}-${k}`, label:`专精 ${k}`, mats:v })) }));
  Object.entries(op.modules).forEach(([code,m],i)=> groups.push({ id:`module-${i}`, title:m.name, sub:`${code} · 模组升级`, stages:['stage_1','stage_2','stage_3'].filter(k=>m[k]).map(k=>({ id:`module-${i}-${k}`, label:`Stage ${k.slice(-1)}`, mats:m[k] })) }));
  return groups;
}

function renderRequirements() {
  const op=operators[state.active], groups=groupsFor(op);
  document.querySelector('#requirements').innerHTML = groups.map(g => {
    const groupMode=uniformMode(g.stages);
    const selectedCount=g.stages.filter(s=>state.selected.has(s.id)).length;
    const groupSelected=selectedCount===g.stages.length;
    const groupPartial=selectedCount>0&&!groupSelected;
    return `<article class="requirement-card panel"><div class="requirement-head"><div><h3>${g.title}</h3><p>${g.sub}</p></div><div class="group-actions">${groupSelectTab(g,groupSelected,groupPartial)}${groupModeTabs(g.id,groupMode)}</div></div>
      <div class="stages">${g.stages.map(s=>{ const mode=state.modes[s.id]||'original'; return `<div class="stage"><div class="stage-top"><label class="check-label"><input type="checkbox" data-stage="${s.id}" ${state.selected.has(s.id)?'checked':''}>${s.label}</label>${modeTabs(s.id,mode)}</div><div class="material-grid">${materialCards(expandList(s.mats,mode))}</div></div>`}).join('')}</div></article>`;
  }).join('') || '<div class="panel empty-state">该干员暂无可展示的培养材料。</div>';
  document.querySelectorAll('[data-mode-group]').forEach(btn => btn.onclick = () => { const group=groups.find(g=>g.id===btn.dataset.modeGroup); group.stages.forEach(s=>state.modes[s.id]=btn.dataset.mode); renderRequirements(); renderSummary(); });
  document.querySelectorAll('[data-select-group]').forEach(btn => btn.onclick = () => {
    const group=groups.find(g=>g.id===btn.dataset.selectGroup);
    const allSelected=group.stages.every(s=>state.selected.has(s.id));
    group.stages.forEach(s=>allSelected?state.selected.delete(s.id):state.selected.add(s.id));
    renderRequirements(); renderSummary();
  });
  document.querySelectorAll('[data-mode-stage]').forEach(btn => btn.onclick = () => { state.modes[btn.dataset.modeStage]=btn.dataset.mode; renderRequirements(); renderSummary(); });
  document.querySelectorAll('[data-stage]').forEach(c => c.onchange = () => { c.checked?state.selected.add(c.dataset.stage):state.selected.delete(c.dataset.stage); renderSummary(); });
  syncMasterControls();
}

function groupSelectTab(group,selected,partial) {
  const label=selected?'已选整组':partial?'补全整组':'选取整组';
  return `<button class="group-select ${selected?'active':''} ${partial?'partial':''}" data-select-group="${group.id}" aria-pressed="${selected}">${label}<small>${group.stages.length} 个阶段</small></button>`;
}

function modeTabs(stageId,active) {
  return `<div class="mode-tabs" role="group" aria-label="材料展开方式">
    <button class="${active==='original'?'active':''}" data-mode-stage="${stageId}" data-mode="original">原始</button>
    <button class="${active==='purple'?'active':''}" data-mode-stage="${stageId}" data-mode="purple">紫色</button>
    <button class="${active==='blue'?'active':''}" data-mode-stage="${stageId}" data-mode="blue">蓝色</button>
  </div>`;
}

function groupModeTabs(groupId,active) {
  return `<div class="group-mode"><span>本组视图</span><div class="mode-tabs" role="group" aria-label="本组材料展开方式">
    <button class="${active==='original'?'active':''}" data-mode-group="${groupId}" data-mode="original">原始</button>
    <button class="${active==='purple'?'active':''}" data-mode-group="${groupId}" data-mode="purple">紫色</button>
    <button class="${active==='blue'?'active':''}" data-mode-group="${groupId}" data-mode="blue">蓝色</button>
  </div></div>`;
}

function uniformMode(stages) {
  const values=[...new Set(stages.map(s=>state.modes[s.id]||'original'))];
  return values.length===1?values[0]:'mixed';
}

function syncMasterControls() {
  const stages=operators[state.active]?groupsFor(operators[state.active]).flatMap(g=>g.stages):[];
  const active=uniformMode(stages);
  document.querySelectorAll('[data-global-mode]').forEach(btn=>btn.classList.toggle('active',btn.dataset.globalMode===active));
}

function rarityLimit(mode){ return mode==='purple'?3:mode==='blue'?2:99; }
function expandOne(name, qty, mode, stack=new Set()) {
  const r=recipes[name]; if(mode==='original'||!r||!r.craftable||r.rarity<=rarityLimit(mode)||stack.has(name)) return {[name]:qty};
  const next=new Set(stack);next.add(name);const out={};
  r.recipe.ingredients.forEach(i=>merge(out,expandOne(i.name,qty*i.quantity/r.recipe.output_quantity,mode,next)));return out;
}
function expandList(list,mode){ const out={};list.forEach(i=>merge(out,expandOne(i.name,i.quantity,mode)));return Object.entries(out).map(([name,quantity])=>({name,quantity})); }
function merge(a,b){ Object.entries(b).forEach(([k,v])=>a[k]=(a[k]||0)+v);return a; }
function safeFile(name){return name.replaceAll('/','／').replaceAll(':','：')+'.png'}
function materialCards(list){ return list.length?list.map(m=>`<div class="material-item"><img src="./assets/materials/${encodeURIComponent(safeFile(m.name))}" alt=""><div><strong>${m.name}</strong><span>需要 × ${m.quantity}</span></div></div>`).join(''):'<span class="empty-state">无普通材料</span>'; }

function renderSummary(){
  const groups=groupsFor(operators[state.active]);const total={};
  groups.forEach(g=>g.stages.filter(s=>state.selected.has(s.id)).forEach(s=>expandList(s.mats,state.summaryMode).forEach(i=>total[i.name]=(total[i.name]||0)+i.quantity)));
  document.querySelectorAll('[data-summary-mode]').forEach(btn=>btn.classList.toggle('active',btn.dataset.summaryMode===state.summaryMode));
  const list=Object.entries(total).map(([name,quantity])=>({name,quantity}));const el=document.querySelector('#summaryMaterials');el.className=`material-grid ${list.length?'':'empty-state'}`;el.innerHTML=list.length?materialCards(list):'勾选上方阶段后，这里会自动汇总材料。';
}
init().catch(err => { document.querySelector('#requirements').innerHTML=`<div class="panel empty-state">数据载入失败：${err.message}</div>`; });
