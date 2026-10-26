<script setup lang="ts">
/**
 * PDV em tela cheia, no formato do caixa desktop:
 *   barra de status · trilho de atalhos · área principal · pedido.
 *
 * A área principal troca DENTRO do PDV (sem janela por cima): catálogo, pedidos da
 * loja, clientes e caixa — as mesmas listas das telas da retaguarda.
 *
 * Dois modos (vem do bootstrap, pela permissão `cash.manage`):
 * - Vendedor: monta o pedido e "Envia ao caixa" (fica guardado); não vê caixa nem cobra.
 * - Caixa: turno aberto obrigatório, cobra, guarda/retoma pedidos e bloqueia a tela
 *   (F12 ou sozinha depois de `lock_minutes` parada; volta só com senha).
 *
 * Teclas: F1 venda · F2 pedidos · F3 cliente · F4 caixa · F5 preço · F6 desconto ·
 * F7 cupom · F8 sair · F9 guardar · F10 pagar/enviar · F12 bloquear.
 * Toda regra está em `usePdv` e no backend; aqui só se desenha.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import type { PaymentInput } from "@/api/sales";
import { salesApi } from "@/api/sales";
import type { PdvProductView, SaleItem } from "@/api/types";
import PromptDialog, { type PromptAnswer, type PromptSpec } from "@/components/common/PromptDialog.vue";
import PdvCashDialog, { type CashMode } from "@/components/pdv/PdvCashDialog.vue";
import PdvCashPanel, { type CashAction } from "@/components/pdv/PdvCashPanel.vue";
import PdvCatalog from "@/components/pdv/PdvCatalog.vue";
import PdvCustomers from "@/components/pdv/PdvCustomers.vue";
import PdvDelivery from "@/components/pdv/PdvDelivery.vue";
import PdvLock from "@/components/pdv/PdvLock.vue";
import PdvOrder from "@/components/pdv/PdvOrder.vue";
import PdvOrders from "@/components/pdv/PdvOrders.vue";
import PdvPaymentDialog from "@/components/pdv/PdvPaymentDialog.vue";
import PdvFreightDialog from "@/components/pdv/PdvFreightDialog.vue";
import PdvPriceDialog from "@/components/pdv/PdvPriceDialog.vue";
import PdvProductDialog from "@/components/pdv/PdvProductDialog.vue";
import PdvRail, { type RailAction } from "@/components/pdv/PdvRail.vue";
import PdvStatusBar from "@/components/pdv/PdvStatusBar.vue";
import { ApprovalCancelled } from "@/composables/useApproval";
import { useNotify } from "@/composables/useNotify";
import { usePdv } from "@/composables/usePdv";
import { type CatalogProduct, usePdvCatalog } from "@/composables/usePdvCatalog";
import { useSession } from "@/stores/session";
import { money } from "@/utils/format";
import { openPrint } from "@/utils/print";
import { CANCEL_SALE_REASONS, PARK_REASONS, REMOVE_ITEM_REASONS } from "@/utils/reasons";

type View = "sale" | "orders" | "customer" | "cash" | "delivery";

const pdv = usePdv();
const catalog = usePdvCatalog();
const session = useSession();
const router = useRouter();
const notify = useNotify();

const catalogRef = ref<InstanceType<typeof PdvCatalog>>();
const view = ref<View>("sale");
const paying = ref(false);
const cashMode = ref<CashMode>("open");
const cashOpen = ref(false);
const priceOpen = ref(false);
const freightOpen = ref(false);
const viewing = ref<PdvProductView | null>(null);
const opening = ref<string | null>(null);
/** Venda recém-concluída: oferece o recibo (F9) ou segue para a próxima (Enter). */
const finished = ref<{ id: string; number: number; change: string; total: string } | null>(null);
const prompt = ref<PromptSpec | null>(null);
let answerPrompt: (value: PromptAnswer | null) => void = () => undefined;

const seller = computed(() => pdv.isSeller.value);
const noCash = computed(() => !pdv.boot.value || pdv.needsCash.value);
/** Aviso "Caixa fechado" (diálogo, não tela): abre no início e pelo selo da barra de status. */
const closedAlert = ref(false);
const myRegisters = computed(() => pdv.boot.value?.cash_registers ?? []);
function openFromAlert() {
  closedAlert.value = false;
  openCashDialog("open");
}
/** Caixa aberto: avisa e imprime o comprovante de abertura (abre a gaveta na térmica). */
function openingDone(id: string) {
  notify.success("Caixa aberto", "Comprovante de abertura enviado para a impressora.");
  openPrint("turno", id, { formato: "80mm", auto: "1" });
}
function managerApproves() {
  void guard(async () => {
    const opened = await pdv.approveOpening("Conferido pelo gerente no PDV");
    closedAlert.value = false;
    if (opened?.status === "open") openingDone(opened.id);
  }, "Abertura não aprovada");
}
const screenLocked = computed(() => pdv.locked.value && !seller.value && Boolean(pdv.boot.value));
const operator = computed(() => session.me?.name ?? "");
const ask = (spec: PromptSpec) => new Promise<PromptAnswer | null>((resolve) => {
  prompt.value = spec;
  answerPrompt = (value) => {
    prompt.value = null;
    resolve(value);
  };
});

async function guard(action: () => Promise<unknown>, title = "Não foi possível concluir") {
  try {
    await action();
  } catch (error) {
    if (!(error instanceof ApprovalCancelled)) notify.error(error, title);
  } finally {
    focusSearch();
  }
}

function focusSearch() {
  if (view.value === "sale") catalogRef.value?.focus();
}

function show(next: View) {
  view.value = next;
  if (next === "sale") setTimeout(focusSearch);
}

/** Cartão clicado: abre SEMPRE a vitrine do produto (fotos, variação, quantidade e, se
 *  houver, os serviços). Venda rápida sem abrir nada continua pelo leitor/código na busca. */
async function pick(product: CatalogProduct) {
  if (opening.value) return;
  opening.value = product.id;
  try {
    viewing.value = await salesApi.productView(product.id);
  } catch (error) {
    notify.error(error, "Produto não carregado");
  } finally {
    opening.value = null;
  }
}

async function confirmView(variant: string, quantity: string, services: string[]) {
  await guard(async () => {
    await pdv.addVariant(variant, quantity, services);
    viewing.value = null;
  }, "Item não lançado");
}

const scan = (value: string) => guard(() => pdv.scan(value), "Item não lançado");

async function removeItem(item: SaleItem) {
  const services = pdv.items.value.filter((i) => i.parent_item === item.id);
  const answer = await ask({
    title: "Remover item", kind: "text", options: REMOVE_ITEM_REASONS, danger: true, confirmLabel: "Remover",
    label: `Por que remover "${item.description}"?${services.length ? ` Os serviços dele (${services.map((s) => s.description).join(", ")}) saem junto.` : ""}`,
  });
  if (answer) await guard(() => pdv.removeItem(item, answer.text ?? ""));
}

async function discount() {
  if (!pdv.sale.value) return;
  const answer = await ask({ title: "Desconto no total", label: "Desconto", kind: "discount", confirmLabel: "Aplicar" });
  if (answer) await guard(() => pdv.discount(answer));
}

async function coupon() {
  if (!pdv.sale.value) return;
  const answer = await ask({ title: "Cupom", label: "Código do cupom (vazio remove)", kind: "text", confirmLabel: "Aplicar" });
  if (answer) await guard(() => pdv.coupon(answer.text || null), "Cupom recusado");
}

async function cancelSale() {
  const answer = await ask({ title: seller.value ? "Cancelar pedido" : "Cancelar venda", label: "Qual o motivo do cancelamento?",
                             kind: "text", required: true, options: CANCEL_SALE_REASONS, danger: true,
                             confirmLabel: seller.value ? "Cancelar pedido" : "Cancelar venda" });
  if (answer) await guard(() => pdv.cancel(answer.text!));
}

/** F9: guarda o pedido para terminar depois (cliente foi buscar algo, fila andando...). */
async function park() {
  if (!pdv.items.value.length) return;
  const answer = await ask({ title: "Guardar pedido", label: "Por que o pedido fica guardado?",
                             kind: "text", confirmLabel: "Guardar", options: PARK_REASONS.slice(1) });
  if (!answer) return;
  await guard(async () => {
    const parked = await pdv.park(answer.text ?? "");
    if (parked) notify.success(`Pedido ${parked.number} guardado`, "Retome em Pedidos (F2) → Guardados.");
  }, "Pedido não guardado");
}

/** Vendedor: o pedido fica guardado na loja e qualquer caixa retoma para cobrar. */
async function send() {
  if (!pdv.items.value.length) return;
  await guard(async () => {
    const parked = await pdv.park("Enviado ao caixa");
    if (parked) notify.success(`Pedido ${parked.number} enviado ao caixa`, `Total ${money(parked.total)}. Já pode atender o próximo.`);
  }, "Pedido não enviado");
}

function openPayment() {
  if (seller.value || noCash.value || !pdv.sale.value || !Number(pdv.sale.value.total)) return;
  paying.value = true;
}

async function pay(payments: PaymentInput[]) {
  await guard(async () => {
    const done = await pdv.checkout(payments);
    paying.value = false;
    finished.value = { id: done.id, number: done.number, change: String(done.change_amount ?? 0), total: String(done.total) };
    void catalog.refresh(); // saldo dos cartões
  }, "Pagamento não concluído");
}

async function resume(id: string) {
  await guard(async () => {
    const sale = await pdv.resume(id);
    notify.success(`Pedido ${sale.number} retomado`);
    show("sale");
  }, "Pedido não retomado");
}

function pickCustomer(body: { customer?: string | null; customer_document?: string }) {
  void guard(async () => {
    await pdv.setCustomer(body);
    show("sale");
  }, "Cliente não vinculado");
}

function applyDelivery(address: string, table: string) {
  void guard(async () => {
    await pdv.setDelivery(address, table);
    notify.success("Entrega lançada", `Frete ${money(pdv.sale.value?.freight ?? 0)} no total.`);
    show("sale");
  }, "Entrega não lançada");
}
function pickup() {
  void guard(async () => {
    await pdv.clearDelivery();
    show("sale");
  }, "Não foi possível tirar a entrega");
}

function openCashDialog(mode: CashMode) {
  cashMode.value = mode;
  cashOpen.value = true;
}

function cashAction(action: CashAction) {
  if (action === "lock") pdv.lock();
  else if (action === "report") {
    if (pdv.session.value) openPrint("turno", pdv.session.value.id, { formato: "80mm" });
  } else openCashDialog(action);
}

async function confirmCash(data: { register?: string; amount: string; reason: string }) {
  await guard(async () => {
    if (cashMode.value === "open") {
      const opened = await pdv.openCash(data.register!, data.amount, data.reason);
      if (opened?.status === "open") openingDone(opened.id);
      else closedAlert.value = true; // não bateu: o aviso pede o gerente
    }
    else if (cashMode.value === "close") {
      const closed = await pdv.closeCash(data.amount);
      // Fechamento cego: o operador não vê a diferença; só se precisa do gerente.
      notify.success("Caixa fechado", closed.status === "pending_approval"
        ? (closed.difference != null ? `Diferença de ${money(closed.difference)}: ` : "Conferência enviada: ")
          + "aguardando aprovação do gerente." : undefined);
    } else {
      await pdv.cashMovement(cashMode.value, data.amount, data.reason);
      notify.success(cashMode.value === "withdrawal" ? "Sangria lançada" : "Suprimento lançado", money(data.amount));
    }
    cashOpen.value = false;
  }, "Operação de caixa não concluída");
}

function printReceipt(id = finished.value?.id) {
  if (id) openPrint("venda", id, { auto: "1" }); // papel: o último escolhido nesta máquina (padrão A4)
  if (finished.value) nextSale();
}
function nextSale() {
  finished.value = null;
  show("sale");
}

async function logout() {
  await session.logout();
  await router.push("/login");
}

function rail(action: RailAction) {
  if (action === "price") priceOpen.value = true;
  else if (action === "freight") freightOpen.value = true;
  else if (action === "backoffice") void (session.pdvFirst ? logout() : router.push("/"));
  else if (action === "cash" && seller.value) return;
  else show(action);
}

/* ---- Bloqueio por inatividade (só o caixa) ---- */
let idleTimer: ReturnType<typeof setTimeout> | undefined;
function touch() {
  clearTimeout(idleTimer);
  const minutes = pdv.boot.value?.lock_minutes ?? 0;
  if (seller.value || !minutes || pdv.locked.value || paying.value) return;
  idleTimer = setTimeout(() => pdv.lock(), minutes * 60_000);
}
watch([() => pdv.boot.value, () => pdv.locked.value, paying], touch);

function onKey(event: KeyboardEvent) {
  touch();
  if (screenLocked.value) return;
  if (finished.value && (event.key === "F9" || event.key === "Enter")) {
    event.preventDefault();
    return event.key === "F9" ? printReceipt() : nextSale();
  }
  const dialogOpen = Boolean(document.querySelector(".p-dialog"));
  if (event.key === "Tab" && view.value === "sale" && !dialogOpen && document.activeElement?.id !== "pdv-scanner") {
    event.preventDefault();
    return focusSearch();
  }
  const actions: Record<string, () => void> = {
    F1: () => rail("sale"), F2: () => rail("orders"), F3: () => rail("customer"), F4: () => rail("cash"),
    F5: () => rail(event.shiftKey ? "freight" : "price"), F6: discount, F7: coupon, F8: () => rail("backoffice"), F9: park,
    F11: () => pdv.sale.value && show("delivery"),
    F10: () => (seller.value ? send() : openPayment()), F12: () => !seller.value && pdv.lock(),
  };
  const action = actions[event.key];
  if (!action) return;
  // A tecla é sempre do PDV (F5 não recarrega a página, F1 não abre a ajuda do navegador),
  // mas com um diálogo aberto ela só vale se for o F10.
  event.preventDefault();
  if (!dialogOpen || event.key === "F10") action();
}

/** Fechar a aba no meio de um pedido: o pedido continua salvo no servidor (volta ao abrir),
 *  mas avisamos para ninguém fechar por engano durante a cobrança. */
function onLeave(event: BeforeUnloadEvent) {
  if (pdv.items.value.length) event.preventDefault();
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  window.addEventListener("pointerdown", touch);
  window.addEventListener("beforeunload", onLeave);
  // PDV opera UMA loja: em "todas as lojas", entra na loja principal do usuário (ou na 1ª dele).
  if (!session.hasConcreteStore) {
    const mine = session.stores.find((st) => st.id === session.me?.default_store_id) ?? session.stores[0];
    if (!mine) return;
    session.setActiveStore(mine.id);
  }
  pdv.setUser(session.me?.id ?? null);
  await guard(() => pdv.init(session.me?.id), "Não foi possível iniciar o PDV");
  if (pdv.needsCash.value && !pdv.locked.value) closedAlert.value = true;
});
onBeforeUnmount(() => {
  clearTimeout(idleTimer);
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("pointerdown", touch);
  window.removeEventListener("beforeunload", onLeave);
});
</script>

<template>
  <div class="pdv">
    <PdvStatusBar :store="session.activeStore?.name ?? 'Selecione uma filial na retaguarda'" :cash-open="!!pdv.session.value"
                  :operator="operator" :since="pdv.session.value?.opened_at ?? null" :seller="seller"
                  :terminal="pdv.boot.value?.terminal?.name ?? ''" @lock="pdv.lock()" @cash="closedAlert = true" />
    <div class="body">
      <PdvRail :active="view === 'delivery' ? 'sale' : view" :seller="seller" :exit-label="session.pdvFirst ? 'Sair' : 'Retaguarda'" @select="rail" />

      <PdvOrders v-if="view === 'orders'" :seller="seller" :busy="pdv.busy.value" @resume="resume"
                 @receipt="(id) => printReceipt(id)" @back="show('sale')" />
      <PdvCustomers v-else-if="view === 'customer'" :busy="pdv.busy.value" @pick="pickCustomer" @back="show('sale')"
                    :current="pdv.sale.value?.customer_name ? { name: pdv.sale.value.customer_name,
                              document: pdv.sale.value.customer_document ?? '' } : null" />
      <PdvDelivery v-else-if="view === 'delivery'" :sale="pdv.sale.value" :busy="pdv.busy.value" @apply="applyDelivery"
                   @pickup="pickup" @customer="show('customer')" @back="show('sale')" />
      <PdvCashPanel v-else-if="view === 'cash' && !seller" :session="pdv.session.value" :operator="operator"
                    :sees-drawer="!!pdv.boot.value?.sees_drawer"
                    @action="cashAction" @back="show('sale')" />
      <PdvCatalog v-else ref="catalogRef" :catalog="catalog" :disabled="(!seller && noCash) || pdv.busy.value"
                  :opening="opening" @pick="pick" @code="scan" />

      <PdvOrder :sale="pdv.sale.value" :items="pdv.items.value" :sellers="pdv.boot.value?.sellers ?? []" :busy="pdv.busy.value"
                :seller="seller" @customer="show('customer')" @seller="(id) => guard(() => pdv.setCustomer({ seller: id }))"
                @quantity="(item, qty) => guard(() => pdv.setQuantity(item, qty))" @remove="removeItem"
                @discount="discount" @coupon="coupon" @pay="openPayment" @cancel="cancelSale" @park="park" @send="send"
                @delivery="show('delivery')" />
    </div>

    <PdvProductDialog :product="viewing" :busy="pdv.busy.value" @confirm="confirmView" @close="viewing = null; focusSearch()" />
    <PdvPriceDialog :visible="priceOpen" @close="priceOpen = false" />
    <PdvFreightDialog :visible="freightOpen" @close="freightOpen = false; focusSearch()" />
    <PdvPaymentDialog v-model:visible="paying" :total="String(pdv.sale.value?.balance_due ?? 0)" :sale="pdv.sale.value"
                      :methods="pdv.boot.value?.payment_methods ?? []" :busy="pdv.busy.value"
                      :has-customer="!!pdv.sale.value?.customer" @confirm="pay" />
    <PdvCashDialog v-model:visible="cashOpen" :mode="cashMode" :registers="pdv.boot.value?.cash_registers ?? []"
                   :busy="pdv.busy.value" @confirm="confirmCash" />
    <Dialog :visible="finished !== null" modal :closable="false" :style="{ width: 'min(420px, calc(100vw - 24px))' }"
            :header="`Venda ${finished?.number} concluída`">
      <div class="done">
        <i class="pi pi-check-circle" />
        <span>Total {{ money(finished?.total) }}</span>
        <strong v-if="Number(finished?.change)">Troco {{ money(finished?.change) }}</strong>
      </div>
      <template #footer>
        <Button severity="secondary" outlined @click="printReceipt()">
          <i class="pi pi-print" /> Imprimir recibo <kbd class="kbd">F9</kbd></Button>
        <Button @click="nextSale"><i class="pi pi-arrow-right" /> Nova venda <kbd class="kbd">Enter</kbd></Button>
      </template>
    </Dialog>
    <Dialog :visible="closedAlert && noCash && !seller && !!pdv.boot.value" modal
            :header="pdv.pendingOpening.value ? 'Abertura aguardando o gerente' : 'Caixa fechado'"
            :style="{ width: 'min(400px, calc(100vw - 24px))' }" @update:visible="closedAlert = false">
      <div class="closed">
        <span class="closed__icon"><i class="pi pi-lock" /></span>
        <template v-if="pdv.pendingOpening.value">
          <p>O dinheiro contado não bate com o que o último fechamento deixou na gaveta. Chame o gerente para
            conferir: ele aprova com a senha dele (ou a senha de ações do caixa).</p>
        </template>
        <template v-else-if="myRegisters.length">
          <p>Para vender, abra o caixa: conte o dinheiro que está na gaveta e informe.</p>
        </template>
        <p v-else>Você não está vinculado a nenhum caixa desta filial. Peça ao gerente para vincular em
          <b>Financeiro → Caixas</b>.</p>
      </div>
      <template #footer>
        <Button label="Agora não" severity="secondary" text @click="closedAlert = false" />
        <Button v-if="pdv.pendingOpening.value" label="Gerente aprova" icon="pi pi-verified" autofocus
                :loading="pdv.busy.value" @click="managerApproves" />
        <Button v-else-if="myRegisters.length" label="Abrir caixa" icon="pi pi-lock-open" autofocus @click="openFromAlert" />
      </template>
    </Dialog>
    <PromptDialog :spec="prompt" @answer="answerPrompt" />
    <PdvLock v-if="screenLocked" :operator="operator" :unlock="pdv.unlock"
             :manager-password="!!pdv.boot.value?.has_cash_action_password" @logout="logout" />
  </div>
</template>

<style scoped>
.pdv { height: 100%; display: flex; flex-direction: column; background: var(--surface-ground); }
.body { flex: 1; display: flex; min-height: 0; }
.closed { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 6px 4px 2px; text-align: center; }
.closed__icon { width: 56px; height: 56px; border-radius: 50%; display: grid; place-items: center; font-size: 22px;
                background: var(--warning-subtle); color: var(--warning-text); }
.closed p { margin: 0; color: var(--text-muted); font-size: 13.5px; }
.done { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 8px 0; }
.done i { font-size: 2.6rem; color: var(--success); }
.done span { color: var(--text-muted); }
.done strong { font-size: 1.8rem; color: var(--text-strong); }
:deep(.p-dialog-footer .p-button) { gap: 6px; }
@media (max-width: 860px) { .body { flex-direction: column; } }
</style>
