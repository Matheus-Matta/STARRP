/**
 * Login = `LoginPage.vue` da retaguarda no celular (≤900px: o painel azul some e o logo vai para cima do
 * formulário): logo, "Entrar", a orientação, usuário com ícone, senha com mostrar/ocultar e "Entrar →".
 * Cantos de cima: ⚙ (esquerda) abre a configuração do servidor; ☀/☾ (direita) troca o tema, como na retaguarda.
 * O servidor vem do `API_URL` do .env (padrão) e pode ser trocado na ⚙ — com "Limpar" e "Testar conexão".
 */
import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import { Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { DEFAULT_SERVER, getServer, normalizeServer, type ServerTest, testServer } from "@/api/client";
import { SafeAreaView } from "@/components/styled";
import { Button, ErrorBox, Sheet } from "@/components/ui";
import { setAppearance } from "@/lib/appearance";
import { tokens, useThemeColors } from "@/lib/tokens";
import { errorMessage } from "@/lib/useApi";
import { useSession } from "@/session/SessionContext";

const LOGO = require("../../assets/brand/logo.png");
const LOGO_DARK = require("../../assets/brand/logo-light.png");

export default function LoginScreen() {
  const { dark } = useThemeColors();
  const insets = useSafeAreaInsets();
  const { signIn } = useSession();
  const [server, setServer] = useState(() => getServer() || DEFAULT_SERVER);
  const [settings, setSettings] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!server.trim()) {
      setSettings(true);
      setError("Informe o endereço do servidor do Starrp (⚙ no canto de cima).");
      return;
    }
    if (!username.trim() || !password) {
      setError("Informe usuário e senha.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await signIn(server, username, password);
    } catch (e) {
      const message = errorMessage(e);
      setError(/no active account|credenciais|credentials/i.test(message) ? "Usuário ou senha inválidos." : message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-ground">
      {/* Cantos de cima: configuração do servidor (esquerda) e tema (direita, `.theme` da retaguarda). */}
      <View className="absolute left-5 right-5 z-10 flex-row justify-between" style={{ top: insets.top + 12 }}>
        <CornerButton icon="settings" label="Configurar servidor" onPress={() => setSettings(true)} />
        <CornerButton icon={dark ? "sun" : "moon"} label={dark ? "Tema claro" : "Tema escuro"}
                      onPress={() => void setAppearance(dark ? "light" : "dark")} />
      </View>

      <KeyboardAvoidingView className="flex-1" behavior={Platform.OS === "ios" ? "padding" : undefined}>
        {/* `.form-side` (padding 2rem) e `.box` (até 400px, gap 1,1rem). */}
        <ScrollView contentContainerClassName="grow items-center justify-center px-8 py-20" keyboardShouldPersistTaps="handled">
          <View className="w-full max-w-[400px] gap-[17.6px]">
            <Image source={dark ? LOGO_DARK : LOGO} className="mb-2 h-[34px] w-[125px]" resizeMode="contain"
                   accessibilityLabel="Starrp" />
            <View>
              <Text className="font-sans-extrabold text-[28px] leading-[30.8px] tracking-[-0.56px] text-strong">Entrar</Text>
              <Text className="mt-1 font-sans text-[13.5px] text-muted">
                Use o usuário e a senha fornecidos pelo administrador da sua filial.
              </Text>
            </View>

            {error && <ErrorBox message={error} />}

            <LoginField label="Usuário" icon="user" value={username} onChangeText={setUsername} autoComplete="username"
                        textContentType="username" returnKeyType="next" />
            <LoginField label="Senha" value={password} onChangeText={setPassword} secure={!reveal} autoComplete="password"
                        textContentType="password" returnKeyType="go" onSubmitEditing={() => void submit()}
                        right={(
                          <Pressable onPress={() => setReveal((r) => !r)} hitSlop={8}
                                     accessibilityLabel={reveal ? "Ocultar senha" : "Mostrar senha"}>
                            <Feather name={reveal ? "eye-off" : "eye"} size={17} color={tokens.subtle} />
                          </Pressable>
                        )} />

            {/* PrimeVue: size="large", fluid, ícone à direita. */}
            <Pressable onPress={() => void submit()} disabled={loading} accessibilityRole="button" accessibilityLabel="Entrar"
                       className={`h-12 flex-row items-center justify-center gap-2 rounded-[7px] bg-brand active:bg-brand-hover${loading ? " opacity-70" : ""}`}>
              <Text className="font-sans-semibold text-[17px] text-on-brand">{loading ? "Entrando…" : "Entrar"}</Text>
              {!loading && <Feather name="arrow-right" size={18} color={tokens.onBrand} />}
            </Pressable>

            <Pressable onPress={() => setSettings(true)} className="flex-row items-center justify-center gap-1.5 py-1">
              <Feather name="server" size={12} color={tokens.subtle} />
              <Text numberOfLines={1} className="font-sans text-[12px] text-subtle">{server || "Servidor não configurado"}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      <ServerDialog visible={settings} value={server} onClose={() => setSettings(false)}
                    onSave={(next) => {
                      setServer(next);
                      setError(null);
                      setSettings(false);
                    }} />
    </SafeAreaView>
  );
}

/** Botão redondo de canto (`.theme` da retaguarda: 40px, raio 10, borda, fundo do cartão). */
function CornerButton({ icon, label, onPress }: { icon: "settings" | "sun" | "moon"; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} accessibilityLabel={label} hitSlop={6}
               className="size-10 items-center justify-center rounded-[10px] border border-border bg-card active:border-brand-border">
      <Feather name={icon} size={17} color={tokens.muted} />
    </Pressable>
  );
}

/** Campo do login (`.field` 13px/600 + InputText grande com ícone à esquerda, como o IconField). */
function LoginField({ label, icon, right, secure, ...props }: {
  label: string; icon?: "user"; right?: React.ReactNode; secure?: boolean; value: string; onChangeText: (v: string) => void;
  autoComplete?: "username" | "password"; textContentType?: "username" | "password"; returnKeyType?: "next" | "go";
  onSubmitEditing?: () => void;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <View className="gap-[6.4px]">
      <Text className="font-sans-semibold text-[13px] text-strong">{label}</Text>
      <View className={`input min-h-12 gap-2.5 px-3.5${focused ? " input-focus" : ""}`}>
        {icon && <Feather name={icon} size={16} color={tokens.subtle} />}
        <TextInput {...props} secureTextEntry={secure} autoCapitalize="none" autoCorrect={false}
                   placeholderTextColor={tokens.subtle} selectionColor={tokens.brand}
                   onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
                   className="input-text flex-1 py-2.5 text-[17px]" />
        {right}
      </View>
    </View>
  );
}

/**
 * Configuração do servidor: o endereço (padrão = API_URL do .env), "Limpar", "Usar o padrão" e "Testar conexão"
 * (chama o /health/ do backend e diz se respondeu, em quanto tempo, ou o que fazer).
 */
function ServerDialog({ visible, value, onClose, onSave }: {
  visible: boolean; value: string; onClose: () => void; onSave: (server: string) => void;
}) {
  useThemeColors();
  const [draft, setDraft] = useState(value);
  const [test, setTest] = useState<ServerTest | null>(null);
  const [testing, setTesting] = useState(false);
  const [wasOpen, setWasOpen] = useState(false);
  if (visible !== wasOpen) {
    setWasOpen(visible);
    if (visible) {
      setDraft(value);
      setTest(null);
    }
  }

  async function runTest() {
    setTesting(true);
    setTest(null);
    setTest(await testServer(draft));
    setTesting(false);
  }

  return (
    <Sheet visible={visible} onClose={onClose} title="Servidor do Starrp"
           footer={(
             <>
               <Button label="Cancelar" variant="outlined-secondary" className="flex-1" onPress={onClose} />
               <Button label="Salvar" icon="check" className="flex-1" disabled={!draft.trim()}
                       onPress={() => onSave(normalizeServer(draft))} />
             </>
           )}>
      <Text className="font-sans text-[13px] text-muted">
        O mesmo endereço da retaguarda (sem /api). No celular, use o IP do computador na rede (ex.: http://192.168.0.10:8001)
        ou o endereço público/túnel — &quot;localhost&quot; é o próprio aparelho.
      </Text>
      <View className="field">
        <Text className="field-label">Endereço do servidor</Text>
        <View className="input gap-2">
          <Feather name="server" size={15} color={tokens.subtle} />
          <TextInput value={draft} onChangeText={(t) => {
            setDraft(t);
            setTest(null);
          }} placeholder={__DEV__ ? "http://192.168.0.10:8001" : "https://app.suaempresa.com.br"} placeholderTextColor={tokens.subtle} autoCapitalize="none"
                     autoCorrect={false} keyboardType="url" selectionColor={tokens.brand} className="input-text flex-1 py-1.5" />
          {draft ? (
            <Pressable hitSlop={8} onPress={() => setDraft("")} accessibilityLabel="Limpar">
              <Feather name="x" size={15} color={tokens.subtle} />
            </Pressable>
          ) : null}
        </View>
        {DEFAULT_SERVER ? <Text className="field-hint">Padrão (API_URL do .env): {DEFAULT_SERVER}</Text> : null}
      </View>

      {/* Ações rápidas */}
      <View className="flex-row flex-wrap gap-2">
        <Button label="Limpar" icon="x-circle" variant="outlined-secondary" compact onPress={() => {
          setDraft("");
          setTest(null);
        }} />
        {DEFAULT_SERVER && draft !== DEFAULT_SERVER ? (
          <Button label="Usar o padrão" icon="rotate-ccw" variant="outlined-secondary" compact onPress={() => {
            setDraft(DEFAULT_SERVER);
            setTest(null);
          }} />
        ) : null}
        <Button label={testing ? "Testando…" : "Testar conexão"} icon="activity" variant="outlined" compact
                loading={testing} disabled={!draft.trim()} onPress={() => void runTest()} />
      </View>

      {test && (
        <View className={test.ok ? "flex-row items-start gap-2 rounded-md bg-success-subtle px-3 py-2.5"
          : "flex-row items-start gap-2 rounded-md bg-danger-subtle px-3 py-2.5"}>
          <Feather name={test.ok ? "check-circle" : "alert-circle"} size={15} color={test.ok ? tokens.successText : tokens.dangerText} />
          <Text className={test.ok ? "flex-1 font-sans-medium text-[13px] text-success-text" : "flex-1 font-sans-medium text-[13px] text-danger-text"}>
            {test.message}
          </Text>
        </View>
      )}
    </Sheet>
  );
}
