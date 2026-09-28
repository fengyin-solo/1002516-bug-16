import { defineStore } from 'pinia'

import { request, OPERATOR_STORAGE_KEY } from '@/api/client'

export interface Operator {
  id: string
  姓名: string
  岗位: string
  当班: boolean
  车站范围: string[]
  权限: string[]
  权限说明: string[]
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '未登录访客',
    operatorId: '',
    shiftLabel: '未当班',
    scope: '（无授权车站）',
    permissions: [] as string[],
    catalog: [] as Operator[],
  }),
  getters: {
    /** 是否具备任意电源屏操作权限；纯只读账号只能查看 */
    canOperate: (state) => state.permissions.length > 0,
  },
  actions: {
    /** 从后端拉取值班名册，并恢复刷新前选中的操作人（台账经手人因此不随刷新改变）。 */
    async loadCatalog() {
      try {
        const response = await request('/api/powersupply/operators')
        if (!response.ok) {
          return
        }
        const payload = (await response.json()) as { items: Operator[] }
        this.catalog = payload.items ?? []
        const savedId = window.localStorage.getItem(OPERATOR_STORAGE_KEY) ?? ''
        if (savedId && this.catalog.some((item) => item.id === savedId)) {
          this.applyOperator(savedId)
        } else {
          this.applyOperator('')
        }
      } catch {
        // 名册拉取失败时保持访客身份，列表仍可读但所有动作会被后端拦下
      }
    },
    selectOperator(operatorId: string) {
      if (operatorId) {
        window.localStorage.setItem(OPERATOR_STORAGE_KEY, operatorId)
      } else {
        window.localStorage.removeItem(OPERATOR_STORAGE_KEY)
      }
      this.applyOperator(operatorId)
    },
    applyOperator(operatorId: string) {
      const found = this.catalog.find((item) => item.id === operatorId)
      this.operatorId = operatorId
      if (found) {
        this.operator = found.姓名
        this.shiftLabel = found.当班 ? '当班' : '非当班'
        this.scope = found.车站范围.includes('*')
          ? '全线各站'
          : found.车站范围.join('、') || '（无授权车站）'
        this.permissions = [...found.权限]
      } else {
        this.operator = '未登录访客'
        this.shiftLabel = '未当班'
        this.scope = '（无授权车站）'
        this.permissions = []
      }
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
