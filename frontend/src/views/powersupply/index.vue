<template>
  <section class="page" data-module="powersupply">
    <header class="page-head">
      <div>
        <h2>信号电源管理</h2>
        <p class="page-desc">
          按所属车站划定操作范围：越站、越权、非当班处理故障、改动停用屏与只读人员改配置都会被拦截；
          每次操作写台账，列表与详情经手人一致，重复操作只生效一次。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="openRecords(undefined)">操作记录台账</button>
        <button class="btn" type="button" @click="exportRows">导出信号电源清单</button>
      </div>
    </header>

    <!-- 当前操作人：身份由服务端目录下发，写操作携带工号，刷新后保留选择 -->
    <div class="identity-bar">
      <label class="filter-item">
        <span>当前操作人（工号 · 姓名 · 车站 · 角色）</span>
        <select v-model="currentId" @change="onChangeOperator">
          <option v-for="op in operators" :key="op.工号" :value="op.工号">
            {{ op.工号 }} · {{ op.姓名 }} · {{ op.所属车站 }} · {{ op.角色 }} ·
            {{ op.当班 ? '当班' : '非当班' }}
          </option>
        </select>
      </label>
      <div class="identity-meta">
        <span class="badge" :class="currentOperator?.当班 ? 'onduty' : 'offduty'">
          {{ currentOperator?.当班 ? '当班中' : '非当班' }}
        </span>
        <span class="muted-text">权限：{{ permissionsText }}</span>
      </div>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>电源屏编号</span>
        <input v-model="filters.keyword" placeholder="按电源屏编号检索" />
      </label>
      <label class="filter-item">
        <span>所属车站</span>
        <input v-model="filters.station" placeholder="按所属车站检索" list="station-options" />
        <datalist id="station-options">
          <option v-for="station in stationOptions" :key="station" :value="station" />
        </datalist>
      </label>
      <label class="filter-item">
        <span>状态</span>
        <input v-model="filters.status" placeholder="供电正常/电压波动/模块故障/备用供电" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '状态'">
              <span class="badge" :class="statusBadge(row.状态)">{{ row.状态 ?? '—' }}</span>
            </template>
            <template v-else-if="column === '投运状态'">
              <span class="badge" :class="row.投运状态 === '已停用' ? 'off' : 'normal'">
                {{ row.投运状态 ?? '—' }}
              </span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="item in actionButtons(row)"
              :key="item.action"
              class="link"
              :class="{ disabled: !item.enabled }"
              type="button"
              :title="item.reason"
              @click="item.enabled && runAction(item.action, row)"
            >
              {{ item.action }}
            </button>
            <button class="link" type="button" @click="openConfig(row)">模块配置</button>
            <button class="link" type="button" @click="openRecords(Number(row.id))">记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无信号电源数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条信号电源记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="okMessage" class="ok-text">{{ okMessage }}</span>
    </footer>

    <!-- 模块配置修改弹窗 -->
    <div v-if="configRow" class="modal-mask" @click.self="configRow = null">
      <div class="modal">
        <div class="modal-head">
          <h3>修改模块配置 · {{ configRow.电源屏编号 }}（{{ configRow.所属车站 }}）</h3>
          <button class="modal-close" type="button" @click="configRow = null">×</button>
        </div>
        <p class="perm-hint">
          需要「模块配置修改」权限且仅可操作本车站在用电源屏；查看人员、越站与停用屏均被禁止。
        </p>
        <div class="form-grid">
          <label class="form-item">
            <span>输入电压</span>
            <input v-model="configForm.输入电压" placeholder="如 AC 380V" />
          </label>
          <label class="form-item">
            <span>模块配置</span>
            <input v-model="configForm.模块配置" placeholder="如 主用模块 A + 备用模块 B" />
          </label>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="configRow = null">取消</button>
          <button class="btn primary" type="button" :disabled="configSaving" @click="saveConfig">
            {{ configSaving ? '提交中…' : '保存配置' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 操作记录台账 / 单屏记录 -->
    <div v-if="recordsOpen" class="modal-mask" @click.self="recordsOpen = false">
      <div class="modal wide">
        <div class="modal-head">
          <h3>{{ recordsTitle }}</h3>
          <button class="modal-close" type="button" @click="recordsOpen = false">×</button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th v-for="column in recordColumns" :key="column">{{ column }}</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rec in records" :key="String(rec.id)">
              <td v-for="column in recordColumns" :key="column">{{ rec[column] ?? '—' }}</td>
              <td><button class="link" type="button" @click="showRecord(Number(rec.id))">经手人详情</button></td>
            </tr>
            <tr v-if="!records.length">
              <td :colspan="recordColumns.length + 1" class="empty-state">暂无操作记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 记录详情：经手人直接取台账同一条记录，保证两处一致 -->
    <div v-if="recordDetail" class="modal-mask" @click.self="recordDetail = null">
      <div class="modal">
        <div class="modal-head">
          <h3>操作记录详情 · {{ recordDetail.记录号 }}</h3>
          <button class="modal-close" type="button" @click="recordDetail = null">×</button>
        </div>
        <table class="kv-table">
          <tbody>
            <tr v-for="field in detailFields" :key="field">
              <th>{{ field }}</th>
              <td>{{ recordDetail[field] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-foot">
          <button class="btn primary" type="button" @click="recordDetail = null">知道了</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { readError, request } from '@/api/client'
import { PERMISSIONS, useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>
type RecordRow = Record<string, string | number | null>

const ENDPOINT = '/api/powersupply'

const columns = [
  '电源屏编号',
  '所属车站',
  '输入电压',
  '输出电压',
  '输出电流',
  '模块配置',
  '切换装置',
  '状态',
  '投运状态',
  '最近操作人',
  '最近动作',
  '最近操作时间',
]

const recordColumns = ['记录号', '电源屏编号', '所属车站', '动作', '操作前状态', '操作后状态', '经手人', '操作时间', '结果']
const detailFields = ['记录号', '电源屏编号', '所属车站', '动作', '操作前状态', '操作后状态', '经手人', '经手人工号', '操作时间', '结果', '请求标识', '备注']

const actionDefs: { action: string; permission: string; fault?: boolean }[] = [
  { action: '登记波动', permission: PERMISSIONS.registerFluctuation },
  { action: '切换备用', permission: PERMISSIONS.switchBackup },
  { action: '处理故障', permission: PERMISSIONS.handleFault, fault: true },
]

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const okMessage = ref('')
const filters = reactive<Record<string, string>>({ keyword: '', station: '', status: '' })
const savingId = ref<number | null>(null)

const operators = computed(() => session.operators)
const currentId = computed({
  get: () => session.currentOperatorId,
  set: (value: string) => session.setCurrentOperator(value),
})
const currentOperator = computed(() => session.currentOperator)
const permissionsText = computed(() =>
  session.permissions.length ? session.permissions.join('、') : '无',
)

const stats = computed(() => [
  { label: '本车站在用屏', value: rows.value.filter((r) => r.投运状态 === '在用' && r.所属车站 === session.operatorStation).length },
  { label: '波动/故障屏', value: rows.value.filter((r) => ['电压波动', '模块故障'].includes(String(r.状态))).length },
  { label: '已停用屏', value: rows.value.filter((r) => r.投运状态 === '已停用').length },
])

const stationOptions = computed(() => Array.from(new Set(rows.value.map((r) => String(r.所属车站)).filter(Boolean))))

// ---------------- 操作人 ----------------
async function loadOperators() {
  try {
    const response = await request(`${ENDPOINT}/operators`)
    if (response.ok) {
      const data = await response.json()
      session.setOperators(data.items ?? [])
    }
  } catch {
    /* 身份目录读不出来时按钮会处于无身份状态，列表仍可查看 */
  }
}

function onChangeOperator() {
  errorMessage.value = ''
  okMessage.value = ''
}

/** 按行计算每个动作按钮是否可用，不可用时给出原因（title），前端先拦，后端再兜底。 */
function actionButtons(row: Row) {
  return actionDefs.map((def) => {
    if (!currentOperator.value) {
      return { action: def.action, enabled: false, reason: '未选择操作人' }
    }
    if (!session.has(def.permission)) {
      return { action: def.action, enabled: false, reason: `缺少「${def.permission}」权限` }
    }
    if (String(row.所属车站) !== session.operatorStation) {
      return { action: def.action, enabled: false, reason: `越站：仅可操作${session.operatorStation}的电源屏` }
    }
    if (row.投运状态 === '已停用') {
      return { action: def.action, enabled: false, reason: '电源屏已停用，禁止改动' }
    }
    if (def.fault && !session.isOnDuty) {
      return { action: def.action, enabled: false, reason: '处理故障只能由当班人员执行' }
    }
    if (def.action === '切换备用' && row.状态 === '备用供电') {
      return { action: def.action, enabled: false, reason: '已处于备用供电，重复操作不生效' }
    }
    if (def.action === '登记波动' && row.状态 !== '供电正常') {
      return { action: def.action, enabled: false, reason: '仅供电正常时可登记波动' }
    }
    return { action: def.action, enabled: true, reason: '' }
  })
}

// ---------------- 列表 ----------------
function resetFilters() {
  filters.keyword = ''
  filters.station = ''
  filters.status = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function reload() {
  errorMessage.value = ''
  okMessage.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.station) params.set('station', filters.station)
  if (filters.status) params.set('status', filters.status)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('电源屏列表读取失败')
    }
    const payload = await response.json()
    // 直接采用后端返回的台账行，最近操作人随列表一起回来，刷新后仍保留
    rows.value = (payload.items ?? []) as Row[]
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '信号电源列表读取失败'
  }
}

// ---------------- 动作 ----------------
async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  okMessage.value = ''
  if (savingId.value !== null) return // 防止连点：同一时间只放一个动作
  savingId.value = Number(row.id)
  // 前端生成幂等键：同一路备用电源的连点/重试用同一个键，服务端只认第一次
  const requestId = `${Number(row.id)}-${action}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, request_id: requestId } }),
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      errorMessage.value = await readError(response, '信号电源操作未生效')
      return
    }
    okMessage.value = data?.message ?? `电源屏已${action}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '信号电源操作失败'
  } finally {
    savingId.value = null
  }
}

// ---------------- 模块配置 ----------------
const configRow = ref<Row | null>(null)
const configForm = reactive<{ 输入电压: string; 模块配置: string }>({ 输入电压: '', 模块配置: '' })
const configSaving = ref(false)

function openConfig(row: Row) {
  if (!currentOperator.value) {
    errorMessage.value = '未选择操作人，无法修改模块配置'
    return
  }
  if (!session.has(PERMISSIONS.editConfig)) {
    errorMessage.value = `越权操作：${currentOperator.value.角色}缺少「模块配置修改」权限`
    return
  }
  if (String(row.所属车站) !== session.operatorStation) {
    errorMessage.value = `越站操作：仅可修改${session.operatorStation}的电源屏配置`
    return
  }
  if (row.投运状态 === '已停用') {
    errorMessage.value = '电源屏已停用，模块配置禁止改动'
    return
  }
  configRow.value = row
  configForm.输入电压 = String(row.输入电压 ?? '')
  configForm.模块配置 = String(row.模块配置 ?? '')
  errorMessage.value = ''
}

async function saveConfig() {
  if (!configRow.value || configSaving.value) return
  configSaving.value = true
  errorMessage.value = ''
  okMessage.value = ''
  const requestId = `cfg-${configRow.value.id}-${Date.now()}`
  try {
    const response = await request(`${ENDPOINT}/${configRow.value.id}/config`, {
      method: 'PUT',
      body: JSON.stringify({
        values: {
          输入电压: configForm.输入电压,
          模块配置: configForm.模块配置,
          request_id: requestId,
        },
      }),
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      errorMessage.value = await readError(response, '模块配置未更新')
      return
    }
    okMessage.value = data?.message ?? '模块配置已更新'
    configRow.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '模块配置更新失败'
  } finally {
    configSaving.value = false
  }
}

// ---------------- 操作记录 ----------------
const recordsOpen = ref(false)
const records = ref<RecordRow[]>([])
const recordsTitle = ref('操作记录台账')
const recordsForEntry = ref<number | undefined>(undefined)
const recordDetail = ref<RecordRow | null>(null)

async function openRecords(entryId?: number) {
  recordsForEntry.value = entryId
  recordsTitle.value = entryId === undefined ? '操作记录台账（全部车站）' : `电源屏操作记录 #${entryId}`
  recordsOpen.value = true
  recordDetail.value = null
  const params = new URLSearchParams({ page: '1', size: '100' })
  if (entryId !== undefined) params.set('entry_id', String(entryId))
  try {
    const response = await request(`${ENDPOINT}/records?${params.toString()}`)
    if (!response.ok) {
      throw new Error('操作记录读取失败')
    }
    const data = await response.json()
    records.value = (data.items ?? []) as RecordRow[]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作记录读取失败'
    records.value = []
  }
}

async function showRecord(recordId: number) {
  try {
    const response = await request(`${ENDPOINT}/records/${recordId}`)
    if (!response.ok) {
      throw new Error('记录详情读取失败')
    }
    recordDetail.value = (await response.json()) as RecordRow
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '记录详情读取失败'
  }
}

// ---------------- 展示辅助 ----------------
function statusBadge(status: unknown): string {
  switch (status) {
    case '供电正常':
      return 'normal'
    case '电压波动':
      return 'warn'
    case '模块故障':
      return 'bad'
    case '备用供电':
      return 'backup'
    default:
      return 'off'
  }
}

onMounted(async () => {
  await loadOperators()
  await reload()
})
</script>
