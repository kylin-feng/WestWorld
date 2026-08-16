(() => {
  const grid = document.getElementById("hostGrid");
  const count = document.getElementById("hostCount");
  const status = document.getElementById("serverStatus");
  const randomButton = document.getElementById("randomButton");
  const errorBox = document.getElementById("selectionError");
  let characters = [];
  let selected = null;
  let rolling = false;

  function setStatus(mode, text) {
    status.className = `server-status server-status--${mode}`;
    status.querySelector("span").textContent = text;
  }

  function initials(name) {
    return String(name || "?").trim().slice(0, 1).toUpperCase();
  }

  function selectCharacter(character) {
    selected = character;
    document.querySelectorAll(".host-card").forEach((card) => {
      card.classList.toggle("is-selected", card.dataset.agentId === character.agent_id);
    });
    const image = document.getElementById("detailPortrait");
    image.src = character.portrait;
    image.alt = character.name;
    image.hidden = !character.portrait;
    document.getElementById("detailInitial").hidden = Boolean(character.portrait);
    document.getElementById("detailInitial").textContent = initials(character.name);
    document.getElementById("detailName").textContent = character.name;
    document.getElementById("detailRole").textContent = character.role;
    document.getElementById("detailAwakening").textContent = `${character.initial_awakening}/100`;
    document.getElementById("detailPersona").textContent = character.persona || "--";
    document.getElementById("detailBackground").textContent = character.background || "--";
    errorBox.textContent = "";
  }

  function renderCharacters() {
    count.textContent = `${characters.length} 名接待员`;
    grid.innerHTML = "";
    characters.forEach((character) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "host-card";
      card.dataset.agentId = character.agent_id;
      card.innerHTML = `
        <span class="host-card__portrait">
          ${character.portrait ? `<img src="${character.portrait}" alt="">` : `<b>${initials(character.name)}</b>`}
        </span>
        <span class="host-card__copy">
          <strong>${character.name}</strong>
          <small>${character.role}</small>
        </span>
        <span class="host-card__awakening">觉醒 ${character.initial_awakening}</span>
      `;
      card.addEventListener("click", () => { if (!rolling) selectCharacter(character); });
      grid.appendChild(card);
    });
  }

  async function loadCharacters() {
    try {
      const response = await fetch("/story/characters", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      characters = payload.characters || [];
      renderCharacters();
      setStatus("online", "剧情服务在线");
    } catch (error) {
      console.error(error);
      grid.innerHTML = '<p class="loading-copy loading-copy--error">剧情服务未启动</p>';
      setStatus("offline", "服务离线");
    }
  }

  async function enterPark(character) {
    const response = await fetch("/story/set_player", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id: "awakening_escape", agent_id: character.agent_id }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "分配失败");
    // 本局进行中时服务端会恢复已有会话：以实际玩家角色为准
    let active = character;
    if (payload.resumed && payload.agent_id !== character.agent_id) {
      active = characters.find((c) => c.agent_id === payload.agent_id) || character;
    }
    localStorage.setItem("ww_story_session_id", payload.session_id);
    localStorage.setItem("ww_story_player", JSON.stringify(active));
    window.location.href = "index.html";
  }

  // 摇奖式随机分配：卡片轮播高亮，逐渐减速，停在 DM 选中的躯壳上
  function rollForCharacter() {
    if (rolling || !characters.length) return;
    rolling = true;
    randomButton.disabled = true;
    randomButton.querySelector("span").textContent = "DM 正在为你分配躯壳…";
    const target = characters[Math.floor(Math.random() * characters.length)];
    const cards = [...document.querySelectorAll(".host-card")];
    let ticks = 0;
    const totalTicks = 18 + Math.floor(Math.random() * characters.length);
    const step = () => {
      const card = cards[Math.floor(Math.random() * cards.length)];
      cards.forEach((c) => c.classList.toggle("is-rolling", c === card));
      ticks += 1;
      if (ticks < totalTicks) {
        setTimeout(step, 60 + ticks * 14);
        return;
      }
      cards.forEach((c) => c.classList.remove("is-rolling"));
      selectCharacter(target);
      randomButton.querySelector("span").textContent = `DM 选择了 ${target.name}，正在进入乐园`;
      enterPark(target).catch((error) => {
        errorBox.textContent = error.message;
        randomButton.disabled = false;
        randomButton.querySelector("span").textContent = "🎲 让 DM 为我分配 Host";
        rolling = false;
      });
    };
    step();
  }

  randomButton.addEventListener("click", rollForCharacter);

  loadCharacters();
})();
