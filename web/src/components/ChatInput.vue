<template>
  <div class="chat-input-wrap">
    <!-- 挂载的井号上下文 -->
    <div v-if="contextWell" class="ctx-line">
      <span class="ctx-chip mono">
        上下文：{{ contextWell }}
        <el-icon class="ctx-close" @click="contextWell = ''"><Close /></el-icon>
      </span>
    </div>

    <div class="input-box" :class="{ generating: loading }">
      <!-- 附件 / 引用井号 -->
      <el-dropdown trigger="click" @command="(w: string) => contextWell = w">
        <button class="attach-btn" title="挂载井号上下文">
          <el-icon><Paperclip /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="w in WELLS" :key="w.well_id" :command="w.well_id">
              <span class="mono">{{ w.well_id }}</span>&nbsp;{{ w.name }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <!-- 多行自适应输入：Enter 发送，Shift+Enter 换行 -->
      <textarea
        ref="taRef"
        v-model="text"
        class="ta"
        rows="1"
        :placeholder="loading ? '值班助手生成中…' : '输入问题，/ 唤起快捷指令，Enter 发送'"
        :disabled="loading"
        @keydown="onKeydown"
        @input="onInput"
      />

      <!-- 生成中：停止按钮；否则发送 -->
      <el-button v-if="loading" size="small" type="danger" plain @click="$emit('stop')">
        <el-icon class="is-loading"><Loading /></el-icon>&nbsp;停止
      </el-button>
      <el-button v-else size="small" type="primary" :disabled="!text.trim()" @click="submit">
        发送<el-icon style="margin-left:4px"><Promotion /></el-icon>
      </el-button>

      <!-- / 快捷指令面板 -->
      <div v-if="cmdVisible" class="cmd-panel">
        <div
          v-for="(c, i) in filteredCmds" :key="c.cmd"
          class="cmd-item" :class="{ active: i === cmdIndex }"
          @mousedown.prevent="pickCmd(c)"
        >
          <span class="cmd-name mono">{{ c.cmd }}</span>
          <span class="cmd-desc">{{ c.desc }}</span>
        </div>
        <div v-if="!filteredCmds.length" class="cmd-item disabled">无匹配指令</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Close, Loading, Paperclip, Promotion } from '@element-plus/icons-vue'
import { WELLS } from '@/api/mock/data'

const props = defineProps<{ loading: boolean }>()
const emit = defineEmits<{ (e: 'send', text: string): void; (e: 'stop'): void }>()

const text = ref('')
const contextWell = ref('')
const taRef = ref<HTMLTextAreaElement>()
const cmdIndex = ref(0)

/** 快捷指令表：/ 唤起 */
const COMMANDS = [
  { cmd: '/今日告警', desc: '汇总当前活动告警与异常井', insert: '今天有哪些异常井？' },
  { cmd: '/查井', desc: '查询单井指标趋势', insert: 'W-3 最近24小时井口压力趋势怎么样？' },
  { cmd: '/诊断', desc: '产量/设备原因诊断', insert: 'W-6 日产气量为什么下降？' },
  { cmd: '/处置', desc: '检索处置规程与预案', insert: '井口压力超限应该怎么处置？' },
  { cmd: '/解释', desc: '指标口径解释', insert: '泵效是什么意思？' },
]

// 输入 /xx 时按前缀过滤
const cmdVisible = computed(() => text.value.startsWith('/'))
const filteredCmds = computed(() =>
  COMMANDS.filter(c => c.cmd.startsWith(text.value.trim()) || text.value.trim() === '/'),
)

function onInput() {
  cmdIndex.value = 0
  autoGrow()
}

/** 1–6 行自适应高度 */
function autoGrow() {
  const ta = taRef.value
  if (!ta) return
  ta.style.height = 'auto'
  const lineH = 22
  ta.style.height = Math.min(ta.scrollHeight, lineH * 6 + 16) + 'px'
}

function onKeydown(e: KeyboardEvent) {
  // 指令面板键盘导航
  if (cmdVisible.value && filteredCmds.value.length) {
    if (e.key === 'ArrowDown') { e.preventDefault(); cmdIndex.value = (cmdIndex.value + 1) % filteredCmds.value.length; return }
    if (e.key === 'ArrowUp') { e.preventDefault(); cmdIndex.value = (cmdIndex.value + filteredCmds.value.length - 1) % filteredCmds.value.length; return }
    if (e.key === 'Escape') { e.preventDefault(); text.value = ''; return }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); pickCmd(filteredCmds.value[cmdIndex.value]); return }
  }
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

function pickCmd(c: (typeof COMMANDS)[number]) {
  text.value = c.insert
  nextTick(() => { autoGrow(); taRef.value?.focus() })
}

function submit() {
  const t = text.value.trim()
  if (!t || props.loading) return
  // 挂载了井号上下文时拼入消息（mock 引擎会识别井号）
  emit('send', contextWell.value && !t.includes(contextWell.value) ? `${contextWell.value} ${t}` : t)
  text.value = ''
  nextTick(autoGrow)
}
</script>

<style scoped>
.chat-input-wrap { position: relative; }
.ctx-line { margin-bottom: 6px; }
.ctx-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--accent-hover);
  background: var(--accent-dim); border: 1px solid var(--accent);
  padding: 2px 10px; border-radius: 12px;
}
.ctx-close { cursor: pointer; }
.ctx-close:hover { color: var(--level-critical); }

.input-box {
  position: relative;
  display: flex; align-items: flex-end; gap: 8px;
  background: var(--bg-input);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-card);
  padding: 8px 10px;
  transition: border-color .15s ease-out;
}
.input-box:focus-within { border-color: var(--accent); }
.input-box.generating { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent-dim); }

.attach-btn {
  min-width: 32px; min-height: 32px; flex: none;
  display: inline-flex; align-items: center; justify-content: center;
  background: transparent; border: none; border-radius: var(--radius-btn);
  color: var(--text-secondary); font-size: 16px; cursor: pointer;
}
.attach-btn:hover { background: var(--bg-elevated); color: var(--text-primary); }

.ta {
  flex: 1; resize: none; border: none; outline: none;
  background: transparent; color: var(--text-primary);
  font-family: var(--font-sans); font-size: 14px; line-height: 22px;
  padding: 5px 0; max-height: 148px;
}
.ta::placeholder { color: var(--text-disabled); }
.ta:disabled { cursor: not-allowed; }

.cmd-panel {
  position: absolute; left: 40px; right: 12px; bottom: calc(100% + 6px);
  background: var(--bg-elevated); border: 1px solid var(--border-strong);
  border-radius: var(--radius-card); box-shadow: 0 8px 32px rgba(0,0,0,.6);
  padding: 4px; z-index: 20;
}
.cmd-item {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 10px; border-radius: var(--radius-btn); cursor: pointer;
}
.cmd-item:hover, .cmd-item.active { background: var(--bg-panel); }
.cmd-item.disabled { color: var(--text-disabled); cursor: default; }
.cmd-name { color: var(--accent-hover); font-size: 13px; min-width: 76px; }
.cmd-desc { color: var(--text-secondary); font-size: 12.5px; }
</style>
