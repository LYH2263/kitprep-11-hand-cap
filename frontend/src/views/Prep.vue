<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const tree = ref<any[]>([])
const orders = ref<any[]>([])
const docs = ref<any[]>([])
const doc = ref<any>(null)
const error = ref('')
const savingId = ref<number | null>(null)

// 行内编辑与弹层各存一份草稿，但保存只走同一个 saveQty —— 口径以后端为准。
const inlineId = ref<number | null>(null)
const inlineDraft = ref<string>('')
const popupId = ref<number | null>(null)
const popupDraft = ref<string>('')

const STATUS_LABEL: Record<string, string> = {
  open: '可改', archived: '已存档', voided: '已作废',
}
const readonly = computed(() => doc.value?.status !== 'open')
const popupLine = computed(() => doc.value?.lines?.find((l: any) => l.id === popupId.value) || null)
const shortageRows = computed(() =>
  (doc.value?.lines || [])
    .map((l: any) => ({ ...l, shortage: Math.max(0, +(l.need_qty - l.stock_qty).toFixed(3)) }))
    .filter((l: any) => l.shortage > 0)
)

async function refreshDocs(selectActive = true) {
  docs.value = await api('/prep/docs?order_id=1')
  if (selectActive) {
    doc.value = await api('/prep/docs/active?order_id=1')
  }
}

async function run() {
  await api('/prep/run?order_id=1', { method: 'POST' })
  error.value = ''
  await refreshDocs(true)
}

function startInline(line: any) {
  inlineId.value = line.id
  inlineDraft.value = String(line.qty)
}
function openPopup(line: any) {
  popupId.value = line.id
  popupDraft.value = String(line.qty)
}
function closeEditors() {
  inlineId.value = null
  popupId.value = null
}

// 唯一保存入口：行内保存与弹层保存都走这里，超需求/作废/存档判定全在后端同一处。
async function saveQty(line: any, draft: string) {
  const qty = Number(draft)
  if (!Number.isFinite(qty)) {
    error.value = '请输入有效数字'
    return
  }
  savingId.value = line.id
  try {
    doc.value = await api(`/prep/docs/${doc.value.id}/lines/${line.id}`, {
      method: 'POST', body: JSON.stringify({ qty }),
    })
    error.value = ''
    closeEditors()
    await refreshDocs(false)
  } catch (e: any) {
    // 整单失败退回：以服务端数据重刷，数量和占用都不会停在半成品状态。
    error.value = e.message
    await refreshDocs(false)
    if (popupId.value === line.id) popupDraft.value = String(popupLine.value?.qty ?? '')
  } finally {
    savingId.value = null
  }
}

async function voidDoc() {
  if (!doc.value || !confirm('作废后该备料单不能再手改，已占用数量会全部释放。确认作废？')) return
  try {
    doc.value = await api(`/prep/docs/${doc.value.id}/void`, { method: 'POST' })
    error.value = ''
    await refreshDocs(false)
  } catch (e: any) {
    error.value = e.message
  }
}

function selectDoc(id: number) {
  const found = docs.value.find((d: any) => d.id === id)
  if (found) { doc.value = found; error.value = ''; closeEditors() }
}

onMounted(async () => {
  tree.value = await api('/bom/tree')
  orders.value = await api('/orders')
  await refreshDocs(true)
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中备料表（数量与占用同改同停）· 右缺料便利贴 · 顶栏订单芯片</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <span v-for="o in orders" :key="o.id" class="kp-chip" style="cursor:default">
      {{ o.code }} · {{ o.outlet }}
    </span>
  </div>
  <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
    <button class="btn" @click="run">生成备料单</button>
    <div class="kp-chips">
      <button v-for="d in docs" :key="d.id" class="kp-chip" type="button"
        :class="{ 'router-link-active': doc?.id === d.id }" @click="selectDoc(d.id)">
        #{{ d.id }} {{ STATUS_LABEL[d.status] || d.status }}
      </button>
    </div>
    <button v-if="doc && !readonly" class="btn"
      style="background:var(--kp-bad);color:#f5ebe0" @click="voidDoc">作废本单</button>
  </div>

  <p v-if="error" class="badge badge-bad" style="margin-top:0.6rem;font-size:0.8rem;padding:0.45rem 0.7rem">
    {{ error }}
  </p>

  <div class="kp-workbench" style="margin-top:0.85rem">
    <aside class="kp-bom-tree">
      <h2>菜品 / BOM</h2>
      <div v-for="d in tree" :key="d.code" class="kp-dish-node">
        <strong>{{ d.dish }}</strong>
        <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
        <ul>
          <li v-for="(c,i) in d.children" :key="i">{{ c.ingredient }} · {{ c.qty }} {{ c.unit }}</li>
        </ul>
      </div>
    </aside>

    <section class="kp-worksheet" v-if="doc">
      <h2>
        备料单 #{{ doc.id }} · {{ doc.order_code }} · {{ doc.outlet }}
        <span class="badge" :class="doc.status === 'open' ? 'badge-ok' : 'badge-warn'">
          {{ STATUS_LABEL[doc.status] || doc.status }}
        </span>
      </h2>
      <p v-if="readonly" class="muted" style="font-size:0.78rem;margin:0 0 0.5rem">
        该单已{{ doc.status === 'voided' ? '作废' : '存档' }}，行数量只读，不能手改。
      </p>
      <table>
        <thead>
          <tr><th>原料</th><th>需求上限</th><th>数量</th><th>占用</th><th>库存</th><th>单位</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="l in doc.lines" :key="l.id">
            <td>{{ l.ingredient_name }}</td>
            <td>{{ l.need_qty }}</td>
            <td>
              <template v-if="!readonly && inlineId === l.id">
                <input v-model="inlineDraft" type="number" min="0" :max="l.need_qty" step="0.001"
                  style="width:5.5rem"
                  @keyup.enter="saveQty(l, inlineDraft)" @keyup.esc="inlineId = null">
              </template>
              <span v-else>{{ l.qty }}</span>
            </td>
            <td>{{ l.reserved_qty }}</td>
            <td>{{ l.stock_qty }}</td>
            <td>{{ l.unit }}</td>
            <td style="white-space:nowrap">
              <template v-if="!readonly">
                <template v-if="inlineId === l.id">
                  <button class="btn" style="padding:0.15rem 0.5rem;font-size:0.72rem"
                    :disabled="savingId === l.id" @click="saveQty(l, inlineDraft)">保存</button>
                  <button class="btn" style="padding:0.15rem 0.5rem;font-size:0.72rem;margin-left:0.25rem"
                    @click="inlineId = null">取消</button>
                </template>
                <template v-else>
                  <button class="btn" style="padding:0.15rem 0.5rem;font-size:0.72rem"
                    @click="startInline(l)">改行</button>
                  <button class="btn" style="padding:0.15rem 0.5rem;font-size:0.72rem;margin-left:0.25rem"
                    @click="openPopup(l)">弹层</button>
                </template>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
    <section v-else class="kp-worksheet">
      <p class="muted">还没有备料单，点击「生成备料单」。</p>
    </section>

    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴</h2>
      <div v-for="r in shortageRows" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!shortageRows.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
    </aside>
  </div>

  <!-- 行上弹层：与行内编辑共用 saveQty，同一接口同一口径 -->
  <div v-if="popupLine"
    style="position:fixed;inset:0;background:rgba(20,16,12,0.55);display:flex;align-items:center;justify-content:center;z-index:50"
    @click.self="popupId = null">
    <div class="card" style="min-width:300px;margin:0">
      <h2 style="margin:0 0 0.5rem;font-size:1rem;border-bottom:2px solid var(--kp-wood);padding-bottom:0.3rem">
        修改 {{ popupLine.ingredient_name }} 数量
      </h2>
      <p class="muted" style="font-size:0.78rem;margin:0 0 0.5rem">
        需求上限 {{ popupLine.need_qty }} {{ popupLine.unit }}；超过上限整单失败退回，占用不动。
      </p>
      <input v-model="popupDraft" type="number" min="0" :max="popupLine.need_qty" step="0.001"
        style="width:100%;padding:0.4rem;margin-bottom:0.6rem"
        @keyup.enter="saveQty(popupLine, popupDraft)" @keyup.esc="popupId = null">
      <div style="display:flex;justify-content:flex-end;gap:0.4rem">
        <button class="btn" @click="popupId = null">取消</button>
        <button class="btn" :disabled="savingId === popupLine.id"
          @click="saveQty(popupLine, popupDraft)">保存</button>
      </div>
    </div>
  </div>
</template>
