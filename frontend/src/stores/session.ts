import { defineStore } from 'pinia'

/** 信号电源操作人：归属车站、角色与当班状态均由后端身份目录下发。 */
export interface OperatorIdentity {
  id: number
  工号: string
  姓名: string
  所属车站: string
  角色: string
  当班: boolean
}

/** 权限点与后端 app/identity.py 保持一致。 */
export const PERMISSIONS = {
  view: '电源屏查看',
  registerFluctuation: '波动登记',
  switchBackup: '备用电源切换',
  handleFault: '故障处理',
  editConfig: '模块配置修改',
} as const

const ROLE_PERMISSIONS: Record<string, string[]> = {
  查看人员: [PERMISSIONS.view],
  值班员: [
    PERMISSIONS.view,
    PERMISSIONS.registerFluctuation,
    PERMISSIONS.switchBackup,
    PERMISSIONS.handleFault,
  ],
  电源管理员: [
    PERMISSIONS.view,
    PERMISSIONS.registerFluctuation,
    PERMISSIONS.switchBackup,
    PERMISSIONS.handleFault,
    PERMISSIONS.editConfig,
  ],
}

const STORAGE_KEY = 'powersupply.operatorId'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '轨道交通信号检修管理平台',
    operators: [] as OperatorIdentity[],
    currentOperatorId: localStorage.getItem(STORAGE_KEY) ?? '',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    currentOperator(state): OperatorIdentity | null {
      return state.operators.find((item) => item.工号 === state.currentOperatorId) ?? null
    },
    operatorName(): string {
      return this.currentOperator ? this.currentOperator.姓名 : '未选择操作人'
    },
    operatorStation(): string {
      return this.currentOperator?.所属车站 ?? ''
    },
    isOnDuty(): boolean {
      return Boolean(this.currentOperator?.当班)
    },
    permissions(): string[] {
      return this.currentOperator ? ROLE_PERMISSIONS[this.currentOperator.角色] ?? [] : []
    },
  },
  actions: {
    setOperators(items: OperatorIdentity[]) {
      this.operators = items
      // 默认选第一个当班人员；若上次选择仍在目录里则保留（刷新后身份不丢）。
      const stillExists = items.some((item) => item.工号 === this.currentOperatorId)
      if (!stillExists) {
        const first = items.find((item) => item.当班) ?? items[0]
        this.currentOperatorId = first ? first.工号 : ''
      }
      this.syncHeader()
    },
    setCurrentOperator(工号: string) {
      this.currentOperatorId = 工号
      localStorage.setItem(STORAGE_KEY, 工号)
      this.syncHeader()
    },
    has(permission: string): boolean {
      return this.permissions.includes(permission)
    },
    /** 当前操作人是否有权操作某台电源屏：先看权限点，再看车站归属，最后看停用/当班。 */
    canActOn(row: { 所属车站?: string; 投运状态?: string }, permission: string): boolean {
      if (!this.currentOperator) return false
      if (!this.has(permission)) return false
      if (row.所属车站 && row.所属车站 !== this.operatorStation) return false
      if (row.投运状态 === '已停用') return false
      return true
    },
    syncHeader() {
      if (this.currentOperator) {
        this.operator = `${this.currentOperator.姓名}（${this.currentOperator.角色}）`
        this.shiftLabel = `${this.currentOperator.所属车站} · ${
          this.currentOperator.当班 ? '当班' : '非当班'
        }`
      } else {
        this.operator = '未选择操作人'
        this.shiftLabel = ''
      }
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
