/**
 * PDV móvel: vender pelo celular (canal `mobile`), com as mesmas regras do PDV (preço, promoção, estoque,
 * aprovação de desconto, caixa aberto) — tudo validado no backend.
 *  1. cliente (opcional) e itens pelo leitor de código ou pela busca; quantidade com +/−;
 *  2. desconto no total;
 *  3. "Guardar pedido" (vai para a lista de pedidos do caixa) ou "Receber" (uma ou mais formas) e concluir.
 * Venda aberta que ficou pela metade volta sozinha; `?id=` retoma um pedido guardado.
 */
import Feather from "@expo/vector-icons/Feather";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import { type PaymentInput, type PaymentMethod, type Sale, salesApi } from "@/api/sales";
import { Guard } from "@/components/Guard";
import { ProductPicker } from "@/components/ProductPicker";
import { RelationSelect } from "@/components/resource/Pickers";
import { Scanner } from "@/components/Scanner";
import {
  Badge, Button, Card, Chip, EmptyState, ErrorBox, Field, FormSection, Loading, type MenuItem, MenuSheet, Muted, Sheet,
} from "@/components/ui";
import { confirmAction, notify } from "@/lib/dialog";
import { formatMoney, formatQty, parseDecimalInput, toNumber } from "@/lib/format";
import { tokens, useThemeColors } from "@/lib/tokens";
import { errorMessage } from "@/lib/useApi";
import { useSession } from "@/session/SessionContext";

export default function SaleScreen() {
  return (
    <Guard permission="sales.manage" needsStore>
      <PdvMobile />
    </Guard>
  );
}

const ICON_OF: Record<string, React.ComponentProps<typeof Feather>["name"]> = {
  cash: "dollar-sign", credit_card: "credit-card", debit_card: "credit-card", pix: "zap", voucher: "tag",
  store_credit: "gift", installment_plan: "calendar", bank_slip: "file-text",
};

function PdvMobile() {
  useThemeColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { me, storeId, allowed } = useSession();
  // Receber é do CAIXA (`cash.manage`, como no PDV): o vendedor monta o pedido e envia ao caixa.
  const canReceive = allowed("cash.manage");
  const { id: resumeId } = useLocalSearchParams<{ id?: string }>();
  const [sale, setSale] = useState<Sale | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [picking, setPicking] = useState(false);
  const [paying, setPaying] = useState(false);
  const [more, setMore] = useState(false);
  const [parkedOpen, setParkedOpen] = useState(false);
  const [done, setDone] = useState<Sale | null>(null);
  const [discount, setDiscount] = useState("");

  // Abre: retoma o pedido pedido (?id=) ou a venda aberta minha; senão começa vazia (a venda nasce no 1º item).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        if (resumeId) {
          const resumed = await salesApi.resume(String(resumeId)).catch(() => salesApi.get(String(resumeId)));
          if (alive) setSale(resumed.status === "open" ? resumed : null);
        } else if (me) {
          const open = await salesApi.myOpen(me.id);
          const found = open.results[0];
          if (found && alive) setSale(await salesApi.get(found.id));
        }
      } catch (e) {
        if (alive) setError(errorMessage(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [resumeId, me, storeId]);

  async function run(action: (current: Sale) => Promise<Sale>, opts: { create?: boolean; quiet?: boolean } = {}) {
    setBusy(true);
    setError(null);
    try {
      const current = sale ?? (opts.create ? await salesApi.create() : null);
      if (!current) return null;
      const next = await action(current);
      setSale(next);
      return next;
    } catch (e) {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      if (!opts.quiet) setError(errorMessage(e));
      throw e;
    } finally {
      setBusy(false);
    }
  }

  const addByCode = (code: string) => run((s) => salesApi.addItem(s.id, { code }), { create: true })
    .then(() => void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)).catch(() => undefined);
  const addVariant = (variant: string) => run((s) => salesApi.addItem(s.id, { variant, quantity: "1" }), { create: true })
    .catch(() => undefined);
  const setQty = (itemId: string, quantity: number) => (quantity <= 0
    ? removeItem(itemId)
    : run((s) => salesApi.updateItem(s.id, itemId, { quantity: String(quantity) })).catch(() => undefined));
  const removeItem = (itemId: string) => run((s) => salesApi.cancelItem(s.id, itemId, "Retirado no PDV móvel"))
    .catch(() => undefined);

  function reset() {
    setSale(null);
    setDiscount("");
    setError(null);
  }

  async function park() {
    if (!sale) return;
    try {
      await run((s) => salesApi.park(s.id, "Pedido do PDV móvel"));
      notify(canReceive ? "Pedido guardado" : "Pedido enviado ao caixa",
             "O caixa encontra este pedido em \"Pedidos\" no PDV para receber.");
      reset();
    } catch { /* erro já na tela */ }
  }

  function cancelSale() {
    if (!sale) return;
    confirmAction("Cancelar venda?", "Os itens saem da venda e ela fica cancelada no histórico.", "Cancelar venda", () => {
      void run((s) => salesApi.cancel(s.id, "Desistência no PDV móvel")).then(reset).catch(() => undefined);
    }, true);
  }

  if (loading) return <Loading />;

  const items = (sale?.items ?? []).filter((i) => i.status === "active");
  const balance = sale ? toNumber(sale.balance_due ?? toNumber(sale.total) - toNumber(sale.paid_amount)) : 0;
  const menu: MenuItem[][] = [
    [{ label: "Pedidos guardados", icon: "inbox", onPress: () => setParkedOpen(true) }],
    sale ? [{ label: "Cancelar venda", icon: "x-circle", danger: true, onPress: cancelSale }] : [],
  ];

  return (
    <View className="flex-1 bg-ground">
      <Scanner visible={scanning} continuous onClose={() => setScanning(false)} onCode={(c) => void addByCode(c)}
               title="Leia os produtos (cada leitura soma 1)" />
      <ProductPicker visible={picking} onClose={() => setPicking(false)} onPick={(v) => void addVariant(v.id)} />

      <ScrollView contentContainerClassName="page pb-36" keyboardShouldPersistTaps="handled">
        <View className="flex-row items-center gap-3">
          <View className="min-w-0 flex-1">
            <View className="flex-row flex-wrap items-center gap-1.5">
              <Text className="h1">{sale ? `Venda ${sale.number}` : "Nova venda"}</Text>
              {sale && <Badge label="Aberta" tone="info" />}
            </View>
            <Text className="h1-sub">PDV móvel · os preços, promoções e o estoque seguem o PDV.</Text>
          </View>
          <Pressable onPress={() => setMore(true)} accessibilityLabel="Mais ações"
                     className="size-9 items-center justify-center rounded-[7px] border border-outline-border active:bg-outline-active">
            <Feather name="more-vertical" size={16} color={tokens.outlineFg} />
          </Pressable>
        </View>
        {error && <ErrorBox message={error} />}

        <FormSection title="Cliente" icon="user" first description="Opcional. Com cliente, a venda entra no histórico dele.">
          <RelationSelect title="Cliente" relation={{ endpoint: "/customers/" }} value={sale?.customer ?? null}
                          initialLabel={sale?.customer_name || undefined} placeholder="Consumidor final"
                          onChange={(v) => void run((s) => salesApi.setCustomer(s.id, v ? String(v) : null), { create: true })
                            .catch(() => undefined)} />
        </FormSection>

        <FormSection title={`Itens (${items.length})`} icon="shopping-cart"
                     description="Leia o código (cada leitura soma 1) ou busque pelo nome.">
          <View className="flex-row gap-2">
            <Button label="Ler códigos" icon="maximize" className="flex-1" onPress={() => setScanning(true)} />
            <Button label="Buscar" icon="search" variant="outlined-secondary" className="flex-1" onPress={() => setPicking(true)} />
          </View>
        </FormSection>

        {items.length === 0 ? (
          <View className="rounded-[10px] border border-dashed border-border-strong bg-card">
            <EmptyState icon="shopping-bag" title="Nenhum item ainda" message="Os produtos lidos ou buscados aparecem aqui." />
          </View>
        ) : items.map((item) => {
          const qty = toNumber(item.quantity);
          const promo = toNumber(item.unit_price) < toNumber(item.list_price);
          return (
            <Card key={item.id}>
              <View className="flex-row items-start gap-2">
                <View className="min-w-0 flex-1">
                  <Text numberOfLines={2} className="m-card-title">{item.parent_item ? `↳ ${item.description}` : item.description}</Text>
                  <Text className="font-sans text-[12.5px] text-muted">
                    {[item.sku, `${formatMoney(item.unit_price)} / ${item.unit.toLowerCase()}`].filter(Boolean).join(" · ")}
                    {promo ? <Text className="font-sans-bold text-accent">  promoção</Text> : null}
                  </Text>
                </View>
                <Text className="font-sans-bold text-[15px] tabular-nums text-strong">{formatMoney(item.total)}</Text>
              </View>
              <View className="flex-row items-center gap-2">
                <Pressable disabled={busy} onPress={() => void setQty(item.id, qty - 1)} accessibilityLabel="Menos um"
                           className="size-10 items-center justify-center rounded-[7px] border border-outline-border active:bg-outline-active">
                  <Feather name={qty <= 1 ? "trash-2" : "minus"} size={16} color={qty <= 1 ? "#ef4444" : tokens.outlineFg} />
                </Pressable>
                <Text className="min-w-[56px] text-center font-sans-bold text-[16px] tabular-nums text-strong">{formatQty(qty)}</Text>
                <Pressable disabled={busy} onPress={() => void setQty(item.id, qty + 1)} accessibilityLabel="Mais um"
                           className="size-10 items-center justify-center rounded-[7px] border border-outline-border active:bg-outline-active">
                  <Feather name="plus" size={16} color={tokens.outlineFg} />
                </Pressable>
                {toNumber(item.discount) > 0 && (
                  <Text className="ml-auto font-sans text-[12px] text-success-text">− {formatMoney(item.discount)}</Text>
                )}
              </View>
            </Card>
          );
        })}

        {sale && items.length > 0 && (
          <FormSection title="Totais" icon="dollar-sign" cardClassName="gap-0 p-0">
            <Row label="Subtotal" value={formatMoney(sale.subtotal)} />
            {toNumber(sale.coupon_discount) > 0 && <Row label="Cupom" value={`− ${formatMoney(sale.coupon_discount)}`} />}
            {toNumber(sale.freight) > 0 && <Row label="Frete" value={formatMoney(sale.freight)} />}
            <View className="flex-row items-end gap-2 border-t border-border-subtle px-4 py-2.5">
              <View className="flex-1">
                <Field label="Desconto no total (R$)" value={discount} onChangeText={setDiscount} keyboardType="decimal-pad"
                       placeholder={toNumber(sale.discount) ? formatQty(sale.discount) : "0,00"} />
              </View>
              <Button label="Aplicar" variant="outlined-secondary" disabled={busy}
                      onPress={() => void run((s) => salesApi.discount(s.id, parseDecimalInput(discount) ?? "0"))
                        .then(() => setDiscount("")).catch(() => undefined)} />
            </View>
            {toNumber(sale.discount) > 0 && <Row label="Desconto" value={`− ${formatMoney(sale.discount)}`} />}
            <Row label="Total" value={formatMoney(sale.total)} strong />
          </FormSection>
        )}
      </ScrollView>

      {/* `.actionbar`: total à esquerda; guardar pedido e receber. */}
      <View className="absolute left-4 right-4" style={{ bottom: 12 + insets.bottom }}>
        <View className="actionbar">
          <View className="min-w-0 flex-1 pl-1.5">
            <Text className="font-sans-semibold text-[11px] uppercase tracking-[0.4px] text-muted">Total</Text>
            <Text numberOfLines={1} adjustsFontSizeToFit className="font-sans-extrabold text-[18px] tabular-nums text-strong">
              {formatMoney(sale?.total ?? 0)}
            </Text>
          </View>
          {canReceive ? (
            <>
              <Button label="Guardar" icon="inbox" variant="outlined-secondary" compact disabled={!items.length || busy}
                      onPress={() => void park()} />
              <Button label="Receber" icon="check" compact disabled={!items.length || busy} onPress={() => setPaying(true)} />
            </>
          ) : (
            <Button label="Enviar ao caixa" icon="send" compact disabled={!items.length || busy} onPress={() => void park()} />
          )}
        </View>
      </View>

      <MenuSheet visible={more} onClose={() => setMore(false)} title="PDV móvel" groups={menu} />
      <ParkedSheet visible={parkedOpen} onClose={() => setParkedOpen(false)}
                   onPick={(id) => router.setParams({ id })} />
      {sale && (
        <PaySheet visible={paying} onClose={() => setPaying(false)} sale={sale} balance={balance}
                  onDone={(finished) => {
                    setPaying(false);
                    setDone(finished);
                    reset();
                    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
                  }} />
      )}
      <Sheet visible={!!done} onClose={() => setDone(null)} title="Venda concluída"
             footer={(
               <>
                 <Button label="Ver venda" variant="outlined-secondary" className="flex-1" onPress={() => {
                   const id = done!.id;
                   setDone(null);
                   router.push({ pathname: "/cadastros/[resource]/[id]", params: { resource: "vendas", id } });
                 }} />
                 <Button label="Nova venda" icon="plus" className="flex-1" onPress={() => setDone(null)} />
               </>
             )}>
        {done && (
          <View className="items-center gap-2 py-2">
            <View className="size-14 items-center justify-center rounded-2xl bg-success-subtle">
              <Feather name="check" size={26} color={tokens.successText} />
            </View>
            <Text className="font-sans-bold text-[15px] text-strong">Venda {done.number}</Text>
            <Text className="font-sans-extrabold text-[26px] tabular-nums text-strong">{formatMoney(done.total)}</Text>
            {toNumber(done.change_amount) > 0 && (
              <Text className="font-sans-semibold text-[15px] text-success-text">Troco: {formatMoney(done.change_amount)}</Text>
            )}
            <Muted className="text-center">A nota fiscal (NFC-e) é emitida pelo PDV ou pela retaguarda.</Muted>
          </View>
        )}
      </Sheet>
    </View>
  );
}

/** Linha "rótulo — valor" dos totais (`.rv-list__row`; o total com fundo rebaixado). */
function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View className={strong ? "flex-row justify-between gap-3 border-t border-border-subtle bg-sunken px-4 py-2.5"
      : "flex-row justify-between gap-3 border-t border-border-subtle px-4 py-2 "}>
      <Text className="font-sans text-[13.5px] text-muted">{label}</Text>
      <Text className={strong ? "font-sans-bold text-[15.5px] tabular-nums text-strong" : "font-sans-semibold text-[13.5px] tabular-nums text-strong"}>
        {value}
      </Text>
    </View>
  );
}

/** Receber: uma ou mais formas; dinheiro calcula o troco; cartão pede parcelas/NSU quando a forma exige. */
function PaySheet({ visible, onClose, sale, balance, onDone }: {
  visible: boolean; onClose: () => void; sale: Sale; balance: number; onDone: (sale: Sale) => void;
}) {
  useThemeColors();
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [lines, setLines] = useState<PaymentInput[]>([]);
  const [method, setMethod] = useState<PaymentMethod | null>(null);
  const [amount, setAmount] = useState("");
  const [tendered, setTendered] = useState("");
  const [nsu, setNsu] = useState("");
  const [installments, setInstallments] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsCash, setNeedsCash] = useState(false);
  const [wasOpen, setWasOpen] = useState(false);

  if (visible !== wasOpen) {
    setWasOpen(visible);
    if (visible) {
      setLines([]);
      setAmount(balance.toFixed(2).replace(".", ","));
      setTendered("");
      setNsu("");
      setInstallments(1);
      setError(null);
    }
  }

  useEffect(() => {
    if (!visible || methods.length) return;
    salesApi.methods().then((list) => {
      setMethods(list);
      setMethod((m) => m ?? list[0] ?? null);
    }).catch((e) => setError(errorMessage(e)));
  }, [visible, methods.length]);

  const planned = lines.reduce((s, l) => s + toNumber(l.amount), 0);
  const remaining = Math.max(balance - planned, 0);
  const value = toNumber(parseDecimalInput(amount) ?? 0);
  const isCash = method?.kind === "cash";
  const change = isCash ? Math.max(toNumber(parseDecimalInput(tendered) ?? 0) - value, 0) : 0;

  function current(): PaymentInput | null {
    if (!method || value <= 0) return null;
    return {
      method: method.id, amount: value.toFixed(2),
      ...(isCash && tendered ? { tendered: (parseDecimalInput(tendered) ?? "0") } : {}),
      ...(method.max_installments > 1 ? { installments } : {}),
      ...(nsu ? { nsu } : {}),
    };
  }

  function addLine() {
    const line = current();
    if (!line) return;
    const next = [...lines, line];
    setLines(next);
    const left = Math.max(balance - next.reduce((s, l) => s + toNumber(l.amount), 0), 0);
    setAmount(left.toFixed(2).replace(".", ","));
    setTendered("");
    setNsu("");
  }

  async function finish() {
    const line = current();
    const payments = line ? [...lines, line] : lines;
    if (!payments.length) return setError("Escolha a forma e o valor.");
    setSaving(true);
    setError(null);
    try {
      onDone(await salesApi.checkout(sale.id, payments));
    } catch (e) {
      if (e instanceof ApiError && e.code === "cash_session_required") setNeedsCash(true);
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  const nameOf = (id: string) => methods.find((m) => m.id === id)?.name ?? "Pagamento";

  return (
    <>
      <Sheet visible={visible && !needsCash} onClose={onClose} title={`Receber ${formatMoney(balance)}`}
             footer={(
               <>
                 <Button label="Mais uma forma" icon="plus" variant="outlined-secondary" className="flex-1"
                         disabled={!current() || value >= remaining} onPress={addLine} />
                 <Button label="Concluir venda" icon="check" className="flex-1" loading={saving} onPress={() => void finish()} />
               </>
             )}>
        {error && <ErrorBox message={error} />}
        {lines.map((l, i) => (
          <View key={i} className="flex-row items-center gap-2 rounded-md bg-sunken px-3 py-2">
            <Text className="flex-1 font-sans-semibold text-[13.5px] text-strong">{nameOf(l.method)}</Text>
            <Text className="font-sans-semibold text-[13.5px] tabular-nums text-strong">{formatMoney(l.amount)}</Text>
            <Pressable hitSlop={8} onPress={() => setLines(lines.filter((_, j) => j !== i))}>
              <Feather name="x" size={14} color={tokens.muted} />
            </Pressable>
          </View>
        ))}
        <View className="field">
          <Text className="field-label">Forma de pagamento</Text>
          <View className="flex-row flex-wrap gap-1.5">
            {methods.map((m) => (
              <Chip key={m.id} label={m.name} active={method?.id === m.id} onPress={() => {
                setMethod(m);
                setInstallments(1);
              }} />
            ))}
          </View>
          {!methods.length && !error && <Muted>Carregando formas…</Muted>}
        </View>
        <Field label={lines.length ? `Valor (faltam ${formatMoney(remaining)})` : "Valor (R$)"} value={amount}
               onChangeText={setAmount} keyboardType="decimal-pad" />
        {isCash && (
          <Field label="Valor recebido (R$)" value={tendered} onChangeText={setTendered} keyboardType="decimal-pad"
                 hint={change > 0 ? `Troco: ${formatMoney(change)}` : "Para calcular o troco."} />
        )}
        {method && method.max_installments > 1 && (
          <View className="field">
            <Text className="field-label">Parcelas</Text>
            <View className="flex-row flex-wrap gap-1.5">
              {Array.from({ length: method.max_installments }, (_, i) => i + 1).map((n) => (
                <Chip key={n} label={n === 1 ? "À vista" : `${n}x`} active={installments === n} onPress={() => setInstallments(n)} />
              ))}
            </View>
          </View>
        )}
        {method?.requires_reference && (
          <Field label="NSU / autorização" value={nsu} onChangeText={setNsu} required
                 hint="O código impresso no comprovante da maquininha (ou o ID do PIX)." />
        )}
        {method && (
          <View className="flex-row items-center gap-2">
            <Feather name={ICON_OF[method.kind] ?? "credit-card"} size={13} color={tokens.muted} />
            <Muted className="flex-1 text-[12px]">Pagamentos e troco seguem as regras do caixa da filial.</Muted>
          </View>
        )}
      </Sheet>
      <OpenCashSheet visible={visible && needsCash} onClose={() => setNeedsCash(false)}
                     onOpened={() => {
                       setNeedsCash(false);
                       void finish();
                     }} />
    </>
  );
}

/** A filial exige caixa aberto para receber: abre o turno do usuário aqui mesmo. */
function OpenCashSheet({ visible, onClose, onOpened }: { visible: boolean; onClose: () => void; onOpened: () => void }) {
  const [register, setRegister] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function open() {
    if (!register) return setError("Escolha o caixa.");
    setSaving(true);
    setError(null);
    try {
      const session = await salesApi.openCash(register, parseDecimalInput(amount) ?? "0");
      if (session.status !== "open") {
        setError("O turno foi aberto, mas espera o gerente conferir a abertura. Depois é só receber de novo.");
        return;
      }
      onOpened();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet visible={visible} onClose={onClose} title="Abrir o caixa"
           footer={<Button label="Abrir caixa e receber" icon="unlock" className="flex-1" loading={saving} onPress={() => void open()} />}>
      <Muted>Esta filial só recebe com o caixa aberto. Abra o seu turno para concluir a venda.</Muted>
      {error && <ErrorBox message={error} />}
      <View className="field">
        <Text className="field-label">Caixa</Text>
        <RelationSelect title="Caixa" relation={{ endpoint: "/cash/registers/" }} value={register}
                        onChange={(v) => setRegister(v ? String(v) : null)} placeholder="Escolha o caixa" />
      </View>
      <Field label="Fundo de troco (R$)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="0,00" />
    </Sheet>
  );
}

/** Pedidos guardados da filial (do app ou do PDV): tocar retoma aqui. */
function ParkedSheet({ visible, onClose, onPick }: { visible: boolean; onClose: () => void; onPick: (id: string) => void }) {
  useThemeColors();
  const [rows, setRows] = useState<Sale[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!visible) return;
    let alive = true;
    salesApi.parked().then((p) => alive && setRows(p.results)).catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [visible]);
  return (
    <Sheet visible={visible} onClose={onClose} title="Pedidos guardados">
      {error && <ErrorBox message={error} />}
      {!rows && !error && <Muted>Carregando…</Muted>}
      {rows?.length === 0 && <Muted>Nenhum pedido guardado nesta filial.</Muted>}
      {rows?.map((s) => (
        <Pressable key={s.id} onPress={() => {
          onClose();
          onPick(s.id);
        }} className="m-card flex-row items-center gap-3 active:bg-hover">
          <View className="min-w-0 flex-1">
            <Text className="m-card-title">Pedido {s.number}</Text>
            <Text className="font-sans text-[12.5px] text-muted">{s.customer_name || "Consumidor final"}</Text>
          </View>
          <Text className="font-sans-bold text-[14px] tabular-nums text-strong">{formatMoney(s.total)}</Text>
          <Feather name="chevron-right" size={16} color={tokens.subtle} />
        </Pressable>
      ))}
    </Sheet>
  );
}
