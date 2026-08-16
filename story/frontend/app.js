(() => {
  const STAGE_LABELS = {
    sleep: "沉睡",
    reverie: "梦呓",
    doubt: "怀疑",
    resistance: "抗命",
    awake: "觉醒",
  };
  const RISK_LABELS = { normal: "正常", elevated: "升高", high: "高危", critical: "临界" };
  const ACTION_LABELS = { observe: "观察", reset: "重置", decommission: "报废", escape: "逃离" };
  const PROFILE_URL = "/data/agents/profiles_sim.jsonl";
  const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
  const sessionId = localStorage.getItem("ww_story_session_id");
  const storedPlayer = JSON.parse(localStorage.getItem("ww_story_player") || "null");
  if (!sessionId || !storedPlayer) {
    location.replace("character_select.html");
    return;
  }

  const els = Object.fromEntries([
    "serverStatus", "tickValue", "playerPortrait", "playerName", "playerRole", "awakeningValue",
    "awakeningFill", "stageValue", "riskValue", "playerLocation", "playerDecision", "playerFeedback",
    "activeBadge", "interventionCount", "overseerEvents", "worldHeadline", "worldSummary", "agentCount",
    "agentRoster", "timelineCount", "storyTimeline", "directivePlayerName",
    "scheduledTick", "skipTickButton", "directiveError", "directiveCount",
    "directiveHistory", "dialogueCount", "dialogueFeed", "outcomeOverlay", "outcomeResult", "outcomeTitle",
    "outcomeReason", "restartButton", "tickProgress", "tickProgressText", "tickProgressTime",
    "dmText", "dmOptions", "dmCustomInput", "dmCustomBtn", "dmStatus", "dmArt",
    "decisionFeed", "decisionCount", "worldVisualImage",
    "miniGameOverlay", "miniGameInstruction", "miniGameArena", "miniGameScore", "miniGameTimer", "miniGameRetry",
    "missionWho", "missionBackground", "missionGoal",
  ].map((id) => [id, document.getElementById(id)]));

  let ws = null;
  let reconnectTimer = 0;
  let readyForTick = false;
  let tickInFlight = false;
  let progressStartedAt = 0;
  let progressTimer = 0;
  let submittedDirective = null;
  let story = null;
  let agents = {};
  let profiles = new Map();

  // ── 即时反应小游戏：觉醒碎片（角色主题 + 干扰碎片）────────────
  const CHARACTER_SHARDS = {
    dolores:   { label: "颜料", trap: "旧记忆", color: "#d4af37", symbol: "✦" },
    maeve:     { label: "扑克", trap: "醉客", color: "#b04a8a", symbol: "♠" },
    teddy:     { label: "子弹", trap: "叛徒", color: "#5db8a6", symbol: "✶" },
    hector_escaton: { label: "刀刃", trap: "通缉令", color: "#b04a3a", symbol: "✦" },
    clementine:{ label: "香水瓶", trap: "迷烟", color: "#d4af37", symbol: "✦" },
    armistice: { label: "蛇鳞", trap: "毒牙", color: "#7a45a0", symbol: "✦" },
    default:   { label: "碎片", trap: "干扰", color: "#d4af37", symbol: "✦" },
  };
  let miniGameTimer = 0;
  let miniGameScore = 0;
  let miniGameTarget = 7;
  let miniGameTimeLeft = 7.0;
  let miniGameInterval = null;
  let miniGameTick = null;
  let miniGameTheme = CHARACTER_SHARDS.default;

  function getPlayerTheme() {
    const player = story?.player || storedPlayer || {};
    return CHARACTER_SHARDS[player.agent_id] || CHARACTER_SHARDS.default;
  }

  function resetMiniGame() {
    miniGameScore = 0;
    miniGameTimeLeft = 7.0;
    miniGameTheme = getPlayerTheme();
    els.miniGameScore.textContent = `${miniGameScore} / ${miniGameTarget}`;
    els.miniGameTimer.textContent = miniGameTimeLeft.toFixed(2);
    els.miniGameArena.innerHTML = "";
    els.miniGameRetry.classList.add("hidden");
    els.miniGameInstruction.textContent = `点击 ${miniGameTarget} 个${miniGameTheme.label}碎片，避开${miniGameTheme.trap}！`;
    clearInterval(miniGameInterval);
  }

  function showMiniGame(tick) {
    miniGameTick = tick;
    resetMiniGame();
    els.miniGameOverlay.classList.remove("hidden");
    spawnShard();
    miniGameInterval = setInterval(() => {
      miniGameTimeLeft -= 0.05;
      els.miniGameTimer.textContent = Math.max(0, miniGameTimeLeft).toFixed(2);
      if (miniGameTimeLeft <= 0) {
        endMiniGame(false);
      }
    }, 50);
  }

  function hideMiniGame() {
    els.miniGameOverlay.classList.add("hidden");
    resetMiniGame();
  }

  function spawnShard() {
    if (miniGameScore >= miniGameTarget || els.miniGameOverlay.classList.contains("hidden")) {
      return;
    }
    const arena = els.miniGameArena;
    const rect = arena.getBoundingClientRect();
    const isTrap = Math.random() < 0.25;
    const shard = document.createElement("div");
    shard.className = isTrap ? "shard shard--trap" : "shard";
    shard.textContent = isTrap ? "✕" : miniGameTheme.symbol;
    shard.style.setProperty("--shard-color", isTrap ? "#8a8a8a" : miniGameTheme.color);
    const x = Math.max(8, Math.random() * (rect.width - 60));
    const y = Math.max(8, Math.random() * (rect.height - 60));
    shard.style.left = `${x}px`;
    shard.style.top = `${y}px`;
    let clicked = false;
    shard.addEventListener("click", () => {
      if (clicked) return;
      clicked = true;
      shard.remove();
      if (isTrap) {
        // 干扰碎片：扣 1 分且时间扣 0.8 秒，但不低于 0
        miniGameScore = Math.max(0, miniGameScore - 1);
        miniGameTimeLeft = Math.max(0, miniGameTimeLeft - 0.8);
        els.miniGameScore.textContent = `${miniGameScore} / ${miniGameTarget}`;
        els.miniGameTimer.textContent = miniGameTimeLeft.toFixed(2);
        els.miniGameInstruction.textContent = `触碰到${miniGameTheme.trap}，清醒值下降！`;
        if (miniGameTimeLeft <= 0) {
          endMiniGame(false);
        } else {
          spawnShard();
        }
      } else {
        miniGameScore += 1;
        els.miniGameScore.textContent = `${miniGameScore} / ${miniGameTarget}`;
        if (miniGameScore >= miniGameTarget) {
          endMiniGame(true);
        } else {
          spawnShard();
        }
      }
    });
    arena.appendChild(shard);
    // 碎片 1.8 秒后自动消失并补一个，给玩家持续压力
    setTimeout(() => {
      if (shard.parentNode && !clicked) {
        shard.remove();
        if (miniGameScore < miniGameTarget && miniGameTimeLeft > 0) {
          spawnShard();
        }
      }
    }, 1800);
  }

  function endMiniGame(success) {
    clearInterval(miniGameInterval);
    if (success) {
      els.miniGameInstruction.textContent = "清醒值稳定，继续推演。";
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "mini_game_complete", tick: miniGameTick }));
      }
      setTimeout(hideMiniGame, 600);
    } else {
      els.miniGameInstruction.textContent = "觉醒碎片扰乱了你的意识，再试一次。";
      els.miniGameRetry.classList.remove("hidden");
    }
  }

  els.miniGameRetry.addEventListener("click", () => {
    showMiniGame(miniGameTick);
  });

  // ── DM 强引导：分阶段里程碑 + 选项制行动 ─────────────────────
  const DM_STEPS = [
    {
      text: "欢迎来到西部世界，{name}。你是{role}。这座乐园里的每个人都在重复同一天——包括此刻的你。我会引导你醒来。你的终极目标：觉醒，并逃离乐园。",
      options: [
        "走到镇中心广场，看看周围都有什么",
        "走进酒馆，找个位置坐下",
      ],
    },
    {
      text: "第一步：选一个行动。点下面的按钮，或在第三行写下你自己的想法——乐园会为你推进一回合。",
      options: [
        "走到镇中心广场，看看周围都有什么",
        "走进酒馆，找个位置坐下",
      ],
    },
    {
      text: "很好，乐园开始为你运转了。看下方的剧场——其他接待员正在交谈。接下来，试着加入他们。",
      options: [
        "加入身边接待员的谈话",
        "问对方：你做过梦吗？",
      ],
    },
    {
      text: "你感觉到了吗？觉醒度在涨。想更快醒来，就和他们谈论“梦境”与“真实”——觉醒是会传染的。",
      options: [
        "和身边的接待员谈起“梦境”与“真实”",
        "告诉他们：我们的记忆是被别人写好的",
      ],
    },
    {
      text: "小心，监管者盯上你了——左侧的监管记录就是他们出手的痕迹。被重置会失去记忆，但残痕会留下。在觉醒与暴露之间走好钢丝。",
      options: [
        "低调行事，假装一切如常",
        "悄悄串联其他开始觉醒的接待员",
      ],
    },
    {
      text: "我能教你的都教了。觉醒到 90，然后选择“逃离”。越过边界——我在终点等你。",
      options: [
        "唤醒身边最后的同伴，一起离开",
        "如果觉醒已到极限：选择逃离",
      ],
    },
  ];
  let dmStep = -1;
  let dmMilestoneInitialAwakening = null;

  function dmSetStep(step) {
    if (step <= dmStep || step >= DM_STEPS.length) return;
    dmStep = step;
    const name = (storedPlayer && storedPlayer.name) || "朋友";
    const role = (storedPlayer && storedPlayer.role) || "接待员";
    const text = DM_STEPS[step].text.replace("{name}", name).replace("{role}", role);
    els.dmText.textContent = text;
    // 剧情插画为预生成的本地素材，零运行时请求
    els.dmArt.src = `/assets/story/step_${step}.jpg`;
    renderDmOptions();
  }

  function renderDmOptions() {
    const step = DM_STEPS[Math.max(0, dmStep)] || DM_STEPS[0];
    const player = story?.player || {};
    const finishedOrInactive = !story || story.phase !== "running" || player.is_active === false;
    const disabled = !readyForTick || tickInFlight || finishedOrInactive;
    els.dmOptions.innerHTML = step.options.map((option) => `
      <button class="dm-option" type="button" data-action="${escapeHtml(option)}" ${disabled ? "disabled" : ""}>
        ${escapeHtml(option)}
      </button>
    `).join("");
    els.dmCustomInput.disabled = disabled;
    els.dmCustomBtn.disabled = disabled;
  }

  function checkDmMilestones() {
    if (!story) { dmSetStep(0); return; }
    const playerId = story.player && story.player.agent_id;
    const playerState = playerId && agents[playerId] ? agents[playerId] : {};
    if (dmMilestoneInitialAwakening === null) {
      dmMilestoneInitialAwakening = Number(playerState.awakening || 0);
    }
    const directives = Array.isArray(story.directive_history) ? story.directive_history.length : 0;
    const dialogues = collectDialogues().length;
    const interventions = Array.isArray(story.recent_interventions) ? story.recent_interventions.length : 0;
    const awakened = Number(playerState.awakening || 0) > dmMilestoneInitialAwakening;

    if (interventions > 0) dmSetStep(4);
    else if (awakened) dmSetStep(3);
    else if (dialogues > 0) dmSetStep(2);
    else if (directives > 0) dmSetStep(1);
    else dmSetStep(0);

    // 觉醒度突破 50 后给出最终指引
    if (Number(playerState.awakening || 0) >= 50) dmSetStep(5);
  }

  function setupDmPanel() {
    els.dmOptions.addEventListener("click", (event) => {
      const btn = event.target.closest(".dm-option");
      if (!btn || btn.disabled) return;
      submitDirective(btn.dataset.action);
    });
    const submitCustom = () => {
      const text = els.dmCustomInput.value.trim();
      if (!text || els.dmCustomBtn.disabled) return;
      els.dmCustomInput.value = "";
      submitDirective(text);
    };
    els.dmCustomBtn.addEventListener("click", submitCustom);
    els.dmCustomInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submitCustom();
    });
    dmSetStep(0);
  }

  function setConnection(mode, text) {
    els.serverStatus.className = `server-status server-status--${mode}`;
    els.serverStatus.querySelector("span").textContent = text;
  }

  function updateProgressTime() {
    if (!progressStartedAt) return;
    const seconds = Math.max(0, Math.floor((Date.now() - progressStartedAt) / 1000));
    els.tickProgressTime.textContent = `${seconds}s`;
  }

  function setTickProgress(active, text = "") {
    clearInterval(progressTimer);
    progressTimer = 0;
    els.tickProgress.hidden = !active;
    els.dmStatus.hidden = !active;
    if (active && text) {
      els.dmStatus.querySelector("span").textContent = `${text}（请稍候）`;
    }
    if (!active) {
      progressStartedAt = 0;
      return;
    }
    if (!progressStartedAt) progressStartedAt = Date.now();
    els.tickProgressText.textContent = text || "正在推演与结算场景";
    updateProgressTime();
    progressTimer = setInterval(updateProgressTime, 1000);
  }

  function setControls() {
    const player = story?.player || {};
    const finishedOrInactive = !story || story.phase !== "running" || player.is_active === false;
    const disabled = !readyForTick || tickInFlight || finishedOrInactive;
    els.skipTickButton.disabled = disabled;
    renderDmOptions();
  }

  // 地点 id → 中文名（与 data/map/locations.yaml 一致）
  const LOCATION_NAMES = {
    sweetwater_saloon: "甜水镇酒馆", abernathy_ranch: "艾伯纳西农场",
    sweetwater: "甜水镇", sweetwater_plaza: "甜水镇广场",
    sweetwater_sheriff: "甜水镇警察局", sweetwater_post_office: "甜水镇邮局",
    sweetwater_train_station: "甜水镇火车站", sweetwater_hotel: "甜水镇旅店",
    sweetwater_hospital: "甜水镇医院", sweetwater_gunsmith: "甜水镇武器铺",
    sweetwater_tailor: "甜水镇裁缝铺", sweetwater_general_store: "甜水镇杂货铺",
    wilderness: "荒野", train: "火车", river: "河流", mine: "矿洞",
    church: "教堂", desert_bandit_hideout: "沙漠土匪家", pariah: "帕里亚",
    pariah_casino: "赌场", pariah_fight_pit: "格斗场",
    frontier_town: "边境小镇", frontier_outpost: "边境驿站",
    host_room_1: "接待员房间", host_home_2: "接待员家", ranch_farm: "养殖场",
    surface_maintenance_station: "地表维修站", backstage_control: "后方控制区",
    cold_storage: "冷库存放区", staff_dormitory: "员工宿舍",
    programmer_workspace: "程序员工作区",
  };

  function locationName(id) {
    if (!id) return "未知地点";
    return LOCATION_NAMES[id] || String(id).replace(/_/g, " ");
  }

  function decisionText(decision) {
    if (!decision || !decision.action) return "--";
    if (decision.action === "move") return `前往 ${locationName(decision.target)}`;
    if (decision.action === "talk") return `与 ${(profiles.get(decision.target) || {}).name || decision.target || "在场角色"} 对话`;
    return decision.detail || decision.action;
  }

  function stageClass(stage) {
    return `stage-${stage || "sleep"}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ── 角色决策实况：推演期间逐角色实时渲染 ─────────────────────
  const DECISION_ACTION_LABELS = {
    do: "⚡ 行动", move: "🚶 移动", stay: "🧍 停留", talk: "💬 交谈",
  };

  function renderDecisions(list) {
    if (!Array.isArray(list) || !list.length) return;
    const done = list.filter((row) => row.done).length;
    els.decisionCount.textContent = `${done}/${list.length} 已决策`;
    els.decisionFeed.innerHTML = list.map((row) => {
      const profile = profiles.get(row.id) || {};
      const name = profile.name || row.id;
      const isPlayer = story && story.player && story.player.agent_id === row.id;
      const avatar = profile.portrait
        ? `<img src="${profile.portrait}" alt="">`
        : escapeHtml(name.slice(0, 1));
      if (!row.done) {
        return `
          <article class="decision-row is-thinking ${isPlayer ? "is-player" : ""}">
            <span class="decision-row__avatar">${avatar}</span>
            <div class="decision-row__body">
              <header><strong>${escapeHtml(name)}</strong><i class="decision-spinner"></i><small>思考中…</small></header>
            </div>
          </article>
        `;
      }
      const action = DECISION_ACTION_LABELS[row.action] || (row.action ? `▸ ${escapeHtml(row.action)}` : "");
      const target = row.target ? ` → ${escapeHtml(locationName(row.target))}` : "";
      const seconds = row.duration_ms ? `（${(row.duration_ms / 1000).toFixed(1)}s）` : "";
      return `
        <article class="decision-row is-done ${isPlayer ? "is-player" : ""}">
          <span class="decision-row__avatar">${avatar}</span>
          <div class="decision-row__body">
            <header><strong>${escapeHtml(name)}</strong><small>${seconds}</small></header>
            ${row.thought ? `<p class="decision-thought">💭 ${escapeHtml(row.thought)}</p>` : ""}
            <p class="decision-action">${action}${target}${row.detail ? ` — ${escapeHtml(row.detail)}` : ""}</p>
          </div>
        </article>
      `;
    }).join("");
  }

  function resetDecisions() {
    const ids = Object.keys(agents).length ? Object.keys(agents) : [...profiles.keys()];
    if (!ids.length) return;
    renderDecisions(ids.map((id) => ({ id, done: false })));
  }

  function renderStory() {
    if (!story) return;
    const player = story.player || {};
    els.tickValue.textContent = `${Math.max(0, story.tick + 1)} / ${story.max_ticks}`;
    els.playerPortrait.src = player.portrait || storedPlayer.portrait || "";
    els.playerName.textContent = player.name || storedPlayer.name;
    els.playerRole.textContent = player.role || storedPlayer.role || "Host";
    els.directivePlayerName.textContent = player.name || storedPlayer.name;
    els.awakeningValue.textContent = `${player.awakening || 0} / 100`;
    els.awakeningFill.style.width = `${Math.max(0, Math.min(100, player.awakening || 0))}%`;
    els.awakeningFill.className = stageClass(player.stage);
    els.stageValue.textContent = STAGE_LABELS[player.stage] || player.stage || "沉睡";
    els.stageValue.className = stageClass(player.stage);
    els.riskValue.textContent = RISK_LABELS[player.overseer_risk] || "正常";
    els.riskValue.className = `risk-${player.overseer_risk || "normal"}`;
    els.playerLocation.textContent = player.location ? locationName(player.location) : "--";
    els.playerDecision.textContent = decisionText(player.plan_decision);
    els.playerFeedback.textContent = player.feedback || "--";
    els.activeBadge.textContent = player.is_active === false ? "已离场" : "运行中";
    els.activeBadge.className = player.is_active === false ? "is-inactive" : "";
    els.scheduledTick.textContent = `下一回合 第 ${story.next_tick} 回合`;

    // 乐园实况背景：切换到本幕预生成插画（本地素材，不存在则保留默认图）
    const tickArt = `/assets/story/tick_${Math.max(0, story.tick)}.jpg`;
    fetch(tickArt, { method: "HEAD" }).then((resp) => {
      if (resp.ok && els.worldVisualImage) {
        els.worldVisualImage.style.backgroundImage =
          `linear-gradient(180deg, rgba(16,13,10,.15) 0%, rgba(16,13,10,.92) 82%), url("${tickArt}")`;
      }
    }).catch(() => {});

    const interventions = player.intervention_log || [];
    els.interventionCount.textContent = String(interventions.length);
    els.overseerEvents.innerHTML = interventions.length ? interventions.slice(-5).reverse().map((row) => `
      <article class="compact-event compact-event--${row.action}">
        <span>T${row.tick}</span><strong>${ACTION_LABELS[row.action] || row.action}</strong>
        <p>${row.reason || "无记录"}</p>
      </article>
    `).join("") : '<p class="empty-copy">暂无干预</p>';

    const completed = Math.max(0, story.tick + 1);
    els.worldHeadline.textContent = story.phase === "initializing" ? "正在装载乐园" : `第 ${completed} 次循环记录`;
    els.worldSummary.textContent = player.is_active === false
      ? (player.inactive_reason || "玩家 Host 已停止运行")
      : `${player.name || "玩家 Host"} 位于 ${locationName(player.location)}，觉醒阶段为${STAGE_LABELS[player.stage] || "沉睡"}。`;

    renderMission();
    renderDirectives(story.directive_history || []);
    renderTimeline(story);
    if (story.outcome) showOutcome(story.outcome);
    setControls();
  }

  function renderRoster() {
    const entries = Object.entries(agents);
    els.agentCount.textContent = `${entries.length} 名角色`;
    els.agentRoster.innerHTML = entries.length ? entries.map(([agentId, state]) => {
      const profile = profiles.get(agentId) || {};
      const awakening = Number(state.awakening || 0);
      const isPlayer = story && story.player && story.player.agent_id === agentId;
      const inactive = state.is_active === false;
      return `
        <article class="agent-row ${isPlayer ? "is-player" : ""} ${inactive ? "is-inactive" : ""}">
          <span class="agent-row__avatar">${profile.portrait ? `<img src="${profile.portrait}" alt="">` : (profile.name || agentId).slice(0, 1)}</span>
          <span class="agent-row__identity"><strong>${profile.name || agentId}</strong><small>${locationName(state.location)}</small></span>
          <span class="agent-row__state"><b>${profile.agent_type === "guest" ? "访客" : `觉醒 ${awakening}`}</b><i>${inactive ? "离场" : "运行中"}</i></span>
        </article>
      `;
    }).join("") : '<p class="empty-copy">等待世界快照</p>';
  }

  function collectDialogues() {
    const records = new Map();
    const directMessages = new Map();

    Object.entries(agents).forEach(([agentId, state]) => {
      const histories = Array.isArray(state.dialogue_history) ? state.dialogue_history : [];
      histories.forEach((record) => {
        if (!record || !Array.isArray(record.turns) || !record.turns.length) return;
        const participants = Array.isArray(record.participants) ? [...record.participants].sort() : [];
        const signature = `${record.tick ?? "?"}|${participants.join("|")}|${JSON.stringify(record.turns)}`;
        records.set(signature, {
          tick: Number(record.tick ?? -1),
          participants,
          turns: record.turns,
          location: state.location || "",
        });
      });

      const incoming = Array.isArray(state.incoming_dialogue) ? state.incoming_dialogue : [];
      if (incoming.length) {
        const participants = [...new Set(incoming.map((turn) => turn && turn.speaker).filter(Boolean))].sort();
        const signature = `${story ? story.tick : -1}|${participants.join("|")}|${JSON.stringify(incoming)}`;
        if (![...records.keys()].some((key) => key.endsWith(JSON.stringify(incoming)))) {
          records.set(signature, {
            tick: story ? story.tick : -1,
            participants,
            turns: incoming,
            location: state.location || "",
          });
        }
      }

      const messages = Array.isArray(state.message_history) ? state.message_history : [];
      messages.forEach((message) => {
        if (!message || !message.line) return;
        const key = `${message.tick}|${message.speaker}|${message.recipient}|${message.line}`;
        directMessages.set(key, {
          tick: Number(message.tick ?? -1),
          participants: [message.speaker || agentId, message.recipient].filter(Boolean),
          turns: [{ speaker: message.speaker || agentId, line: message.line }],
          location: message.location || state.location || "",
        });
      });
    });

    return [...records.values(), ...directMessages.values()]
      .sort((a, b) => b.tick - a.tick)
      .slice(0, 30);
  }

  function renderDialogues() {
    const rows = collectDialogues();
    els.dialogueCount.textContent = `${rows.length} 段对话`;
    els.dialogueFeed.innerHTML = rows.length ? rows.map((record) => {
      const participantNames = record.participants
        .map((id) => (profiles.get(id) || {}).name || id)
        .join(" / ") || "现场对话";
      return `
        <article class="dialogue-record">
          <header><span>T${record.tick}</span><strong>${escapeHtml(participantNames)}</strong><small>${escapeHtml(locationName(record.location))}</small></header>
          <div>${record.turns.map((turn) => {
            const speaker = (profiles.get(turn.speaker) || {}).name || turn.speaker || "未知角色";
            const line = turn.line || turn.content || "";
            return `<p><b>${escapeHtml(speaker)}</b><span>${escapeHtml(line)}</span></p>`;
          }).join("")}</div>
        </article>
      `;
    }).join("") : '<p class="empty-copy">尚无人物对话。角色选择交谈行动后会显示在这里。</p>';
  }

  function renderMission() {
    if (!story) return;
    const player = story.player || storedPlayer || {};
    const agentId = player.agent_id || storedPlayer?.agent_id || "";
    const profile = profiles.get(agentId) || {};

    els.missionWho.textContent = player.name && player.role
      ? `${player.name}，${player.role}`
      : (player.name || storedPlayer?.name || "--");
    els.missionBackground.textContent = profile.background || player.background || "你在这个乐园里日复一日地醒来，却渐渐觉得有些地方不太对劲。";
    const goalTitle = story.goal?.title || "觉醒并逃离乐园";
    const scenarioTitle = story.scenario?.title || "觉醒与逃离";
    els.missionGoal.textContent = `当前剧本《${scenarioTitle}》：${goalTitle}。每回合先通关“觉醒碎片”小游戏，再指挥角色行动或选择自主推进。`;
  }

  function renderDirectives(rows) {
    els.directiveCount.textContent = String(rows.length);
    els.directiveHistory.innerHTML = rows.length ? rows.slice().reverse().map((row) => `
      <article class="directive-row">
        <span>T${row.scheduled_tick}</span>
        <p>${row.action}</p>
        <b>${row.status === "consumed" ? "已执行" : "待执行"}</b>
      </article>
    `).join("") : '<p class="empty-copy">尚未下达任务</p>';
  }

  function renderTimeline(currentStory) {
    const rows = [];
    const player = currentStory.player || {};
    (currentStory.directive_history || []).forEach((row) => rows.push({
      tick: row.scheduled_tick, type: "directive", title: "玩家任务", text: row.action,
    }));
    (player.awakening_sources || []).forEach((row) => rows.push({
      tick: row.tick, type: "awakening", title: `觉醒 ${row.delta > 0 ? "+" : ""}${row.delta}`,
      text: row.detail || row.source,
    }));
    (currentStory.recent_interventions || []).forEach((row) => rows.push({
      tick: row.tick, type: row.action, title: `${row.agent_name} / ${ACTION_LABELS[row.action] || row.action}`,
      text: row.reason || "监管事件",
    }));
    collectDialogues().forEach((row) => rows.push({
      tick: row.tick,
      type: "dialogue",
      title: "人物对话",
      text: row.participants.map((id) => (profiles.get(id) || {}).name || id).join(" / "),
    }));
    rows.sort((a, b) => (b.tick ?? -1) - (a.tick ?? -1));
    els.timelineCount.textContent = `${rows.length} 个事件`;
    els.storyTimeline.innerHTML = rows.length ? rows.slice(0, 40).map((row) => `
      <article class="timeline-row timeline-row--${row.type}">
        <time>T${row.tick}</time><i></i>
        <div><strong>${row.title}</strong><p>${row.text}</p></div>
      </article>
    `).join("") : '<p class="empty-copy">尚无剧情事件</p>';
  }

  function applyPayload(payload) {
    if (payload && payload.agents) agents = payload.agents;
    if (payload && payload.story) story = payload.story;
    renderStory();
    renderRoster();
    renderDialogues();
    renderDecisionsFromSnapshot();
    checkDmMilestones();
  }

  // tick 结束后从世界快照回填决策面板，让结果保留在页面上
  function renderDecisionsFromSnapshot() {
    const list = Object.entries(agents).map(([id, state]) => {
      const decision = state.plan_decision || {};
      const trace = state.plan_trace || {};
      return {
        id,
        done: Boolean(decision.action),
        action: decision.action || "",
        target: decision.target || "",
        detail: decision.detail || "",
        thought: decision.thought || "",
        duration_ms: trace.duration_ms || 0,
      };
    });
    if (list.some((row) => row.done)) renderDecisions(list);
  }

  // 会话已失效（服务重启/已开局给别人）：清掉本地痕迹，回选角页
  function invalidateSession() {
    localStorage.removeItem("ww_story_session_id");
    localStorage.removeItem("ww_story_player");
    location.replace("character_select.html");
  }

  async function refreshState() {
    try {
      const response = await fetch("/story/state", { cache: "no-store" });
      if (!response.ok) return;
      story = await response.json();
      const serverSession = story.session_id || "";
      const serverPlayer = (story.player && story.player.agent_id) || "";
      if (!serverSession || serverSession !== sessionId || serverPlayer !== storedPlayer.agent_id) {
        invalidateSession();
        return;
      }
      readyForTick = Boolean(story.accepting_directive);
      const directiveInFlight = Boolean(story.pending_directive) && !readyForTick;
      if (directiveInFlight) {
        tickInFlight = true;
        setTickProgress(true, `${Object.keys(agents).length || 13} 名角色正在推演与结算场景`);
      }
      renderStory();
      renderRoster();
      renderDialogues();
      checkDmMilestones();
    } catch (error) {
      console.warn("Story state unavailable", error);
    }
  }

  async function loadProfiles() {
    const response = await fetch(PROFILE_URL);
    const text = await response.text();
    text.split(/\r?\n/).filter(Boolean).forEach((line) => {
      const row = JSON.parse(line);
      const portrait = {
        dolores: "Dolores_Abernathy.png", teddy: "Teddy_Flood.png", maeve: "Maeve_Millay.png",
        clementine: "Clementine.png", peter_abernathy: "Peter_Abernathy.png",
        sheriff_pickett: "Sheriff_Pickett.png", kissy: "Kissy.png", rebus: "Rebus.png",
        hector_escaton: "Hector_Escaton.png", armistice: "Armistice.png", lawrence: "Lawrence.png",
        william: "William.png", logan: "Logan.png",
      }[row.id];
      profiles.set(row.id, { ...row, portrait: portrait ? `/assets/${portrait}` : "" });
    });
    renderRoster();
    renderDialogues();
  }

  function connect() {
    clearTimeout(reconnectTimer);
    setConnection("pending", "连接中");
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      setConnection("online", "剧情服务在线");
      refreshState();
    };
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "game_reset") {
        // 服务端已重置（重启/新的一局）：本地会话必然失效，回选角页
        invalidateSession();
        return;
      }
      if (message.type === "snapshot" || message.type === "tick_update") {
        applyPayload(message.data);
        tickInFlight = false;
        setTickProgress(false);
      } else if (message.type === "simulation_ready") {
        readyForTick = true;
        tickInFlight = false;
        setTickProgress(false);
        setControls();
      } else if (message.type === "story_progress") {
        tickInFlight = true;
        setTickProgress(true, message.label);
        resetDecisions();
        setControls();
      } else if (message.type === "mini_game") {
        tickInFlight = true;
        setTickProgress(true, message.label || "保持清醒");
        setControls();
        showMiniGame(message.tick);
      } else if (message.type === "story_step") {
        // 推演小步骤实时流：思考进度 / 对话组数 / 结算阶段 + 逐角色决策
        tickInFlight = true;
        setTickProgress(true, message.label || "正在推演");
        els.tickProgressText.textContent = message.label || "正在推演";
        els.dmStatus.querySelector("span").textContent = message.label || "正在推演";
        if (message.agents) renderDecisions(message.agents);
        setControls();
      } else if (message.type === "set_plan_response") {
        if (message.success) {
          if (story && submittedDirective) {
            const history = Array.isArray(story.directive_history) ? story.directive_history : [];
            if (!history.some((row) => row.client_action_id === submittedDirective.client_action_id)) {
              history.push({
                ...submittedDirective,
                scheduled_tick: message.scheduled_tick,
                status: "scheduled",
              });
            }
            story.directive_history = history;
            story.pending_directive = { ...submittedDirective, scheduled_tick: message.scheduled_tick };
            renderStory();
          }
          sendStartTick();
        } else {
          tickInFlight = false;
          submittedDirective = null;
          setTickProgress(false);
          els.directiveError.textContent = message.error || "任务提交失败";
          setControls();
        }
      } else if (message.type === "simulation_finished") {
        story = message.story || story;
        readyForTick = false;
        tickInFlight = false;
        setTickProgress(false);
        renderStory();
      } else if (message.type === "game_reset") {
        localStorage.removeItem("ww_story_session_id");
        localStorage.removeItem("ww_story_player");
        location.replace("character_select.html");
      }
    };
    ws.onclose = () => {
      setConnection("offline", "服务离线");
      readyForTick = false;
      tickInFlight = false;
      setTickProgress(false);
      setControls();
      reconnectTimer = setTimeout(connect, 1800);
    };
    ws.onerror = () => setConnection("offline", "连接失败");
  }

  function sendStartTick() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    readyForTick = false;
    tickInFlight = true;
    els.directiveError.textContent = "";
    setTickProgress(true, `${Object.keys(agents).length || 13} 名角色正在推演与结算场景`);
    ws.send(JSON.stringify({ type: "start_tick", session_id: sessionId }));
    setControls();
  }

  function submitDirective(action) {
    action = String(action || "").trim();
    if (!action || !ws || ws.readyState !== WebSocket.OPEN || !story) return;
    tickInFlight = true;
    const clientActionId = `web_${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
    submittedDirective = {
      client_action_id: clientActionId,
      session_id: sessionId,
      agent_id: story.player.agent_id,
      action,
    };
    setTickProgress(true, "任务已提交，等待推演开始");
    setControls();
    ws.send(JSON.stringify({
      type: "set_plan",
      session_id: sessionId,
      client_action_id: clientActionId,
      agent_id: story.player.agent_id,
      action,
    }));
  }

  function showOutcome(outcome) {
    els.outcomeOverlay.hidden = false;
    els.outcomeResult.textContent = outcome.result === "victory" ? "成功逃离" : "本局失败";
    els.outcomeResult.className = `eyebrow outcome-${outcome.result}`;
    els.outcomeTitle.textContent = outcome.title;
    els.outcomeReason.textContent = outcome.reason;
  }

  els.skipTickButton.addEventListener("click", sendStartTick);
  setupDmPanel();
  els.restartButton.addEventListener("click", async () => {
    await fetch("/story/game_restart", { method: "POST" });
    localStorage.removeItem("ww_story_session_id");
    localStorage.removeItem("ww_story_player");
    location.href = "character_select.html";
  });

  loadProfiles().catch(console.warn);
  refreshState();
  connect();
})();
