<template>
  <section class="page" data-module="powersupply">
    <header class="page-head">
      <div>
        <h2>信号电源管理</h2>
        <p class="page-desc">
          按所属车站划定可操作范围：越站、缺权限、非当班处理故障、操作已停用电源屏都会被拦下。
          当前身份：{{ session.operator }}（{{ session.shiftLabel }}，范围：{{ session.scope }}）
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记电源屏</button>
        <button class="btn" type="button" @click="exportRows">导出信号电源清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="item in actionPerms(row)"
              :key="item.动作"
              class="link"
                  type="button"
                  :disabled="!item.允许"
                  :title="item.允许 ? '' : item.拦截原因"
                  @click="runAction(item.动作, row)"
                >
                  {{ item.动作 }}
                </button>
              </td>
              <td class="row-actions">
                <button class="link" type="button" @click="openDetail(row)">记录详情</button>
                <button
                  class="link"
                  type="button"
                  :disabled="!canEdit(row)"
                  :title="canEdit(row) ? '' : editBlockReason(row)"
                  @click="openConfig(row)"
                >
                  修改配置
                </button>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td :colspan="columns.length + 2" class="empty-state">暂无信号电源数据，可先登记电源屏</td>
            </tr>
          </tbody>
        </table>

        <footer class="page-foot">
          <span>共 {{ total }} 条信号电源记录</span>
          <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
        </footer>

        <div v-if="detailRow" class="modal-mask" @click.self="closeDetail">
          <div class="modal">
            <h3>切换记录详情 · {{ detailRow['电源屏编号'] }}</h3>
            <p class="modal-meta">
              所属车站：{{ detailRow['所属车站'] }} ｜ 当前状态：{{ detailRow.status }} ｜
              台账经手人：{{ detailRow['经手人'] ?? '—' }}
            </p>
            <table class="data-table">
              <thead>
                <tr><th>时间</th><th>经手人</th><th>动作</th><th>说明</th></tr>
              </thead>
              <tbody>
                <tr v-for="(record, index) in detailRow['操作记录'] ?? []" :key="index">
                  <td>{{ record['时间'] }}</td>
                  <td>{{ record['经手人'] }}</td>
                  <td>{{ record['动作'] }}</td>
                  <td>{{ record['说明'] }}</td>
                </tr>
                <tr v-if="!(detailRow['操作记录'] ?? []).length">
                  <td colspan="4" class="empty-state">暂无操作记录</td>
                </tr>
              </tbody>
            </table>
            <div class="modal-actions">
              <button class="btn" type="button" @click="closeDetail">关闭</button>
            </div>
          </div>
        </div>

        <div v-if="configRow" class="modal-mask" @click.self="closeConfig">
          <div class="modal">
            <h3>修改模块配置 · {{ configRow['电源屏编号'] }}</h3>
            <p class="modal-meta">
              {{ configRow['所属车站'] }} ｜ 需要「模块配置修改权限」且车站归属一致
            </p>
            <form class="config-form" @submit.prevent="submitConfig">
              <label class="filter-item">
                <span>输入电压</span>
                <input v-model="configForm['输入电压']" placeholder="如 AC380V" />
              </label>
              <label class="filter-item">
                <span>模块配置</span>
                <input v-model="configForm['模块配置']" placeholder="如 主模块A×2、监控模块×1" />
              </label>
              <div class="modal-actions">
                <button class="btn primary" type="submit">保存配置</button>
                <button class="btn ghost" type="button" @click="closeConfig">取消</button>
              </div>
            </form>
          </div>
        </div>
      </section>
    </template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

interface ActionPerm {
  动作: string
  允许: boolean
  拦截原因: string
}
interface OperationRecord {
  时间: string
  经手人: string
  动作: string
  说明: string
}
interface DetailData {
  id: number
  status: string
  电源屏编号?: string
  所属车站?: string
  经手人?: string
  操作记录?: OperationRecord[]
  [key: string]: string | number | null | OperationRecord[] | undefined
}
type Row = Record<string, string | number | null | ActionPerm[] | OperationRecord[]>

const ENDPOINT = '/api/powersupply'
const columns = [
  '电源屏编号', '所属车站', '输入电压', '输出电压', '输出电流',
  '模块配置', '切换装置', '电源状态', '启用状态', '经手人',
]
const stats = [
  { label: '正常电源屏', value: 0 },
  { label: '波动电源屏', value: 0 },
  { label: '故障电源屏', value: 0 },
]

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const detailRow = ref<DetailData | null>(null)
const configRow = ref<Row | null>(null)
const configForm = reactive<Record<string, string>>({ 输入电压: '', 模块配置: '' })

function actionPerms(row: Row): ActionPerm[] {
  return (row['可执行动作'] as ActionPerm[] | undefined) ?? []
}

function findPerm(row: Row, action: string): ActionPerm {
  return (
    actionPerms(row).find((item) => item.动作 === action) ?? {
      动作: action,
      允许: false,
      拦截原因: '授权信息缺失，请刷新列表',
    }
  )
}

function canEdit(row: Row): boolean {
  return findPerm(row, '修改配置').允许
}

function editBlockReason(row: Row): string {
  return findPerm(row, '修改配置').拦截原因
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '电源屏登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 越权、重复操作、已停用等业务拦截：展示后端给出的具体原因
      throw new Error(payload.message || '信号电源动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '信号电源操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('电源屏列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '信号电源列表读取失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('记录详情读取失败')
    }
    detailRow.value = (await response.json()) as DetailData
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '记录详情读取失败'
  }
}

function closeDetail() {
  detailRow.value = null
}

function openConfig(row: Row) {
  configRow.value = row
  configForm['输入电压'] = String(row['输入电压'] ?? '')
  configForm['模块配置'] = String(row['模块配置'] ?? '')
}

function closeConfig() {
  configRow.value = null
}

async function submitConfig() {
  if (!configRow.value) {
    return
  }
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${configRow.value.id}/config`, {
      method: 'POST',
      body: JSON.stringify({
        values: { 输入电压: configForm['输入电压'], 模块配置: configForm['模块配置'] },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '配置未更新，请稍后重试')
    }
    closeConfig()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '模块配置修改失败'
  }
}

// 切换身份后重新拉取，逐行授权结果按新身份刷新
watch(
  () => session.operatorId,
  () => {
    void reload()
    detailRow.value = null
    closeConfig()
  },
)

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 720px;
  max-height: 80vh;
  overflow: auto;
  background: #fff;
  border-radius: 8px;
  padding: 18px 20px;
}
.modal h3 { margin: 0 0 8px; font-size: 16px; }
.modal-meta { color: var(--muted); font-size: 13px; margin: 0 0 12px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }
.config-form { display: flex; flex-direction: column; gap: 10px; }
.link:disabled { color: #9aa4b2; cursor: not-allowed; }
</style>
