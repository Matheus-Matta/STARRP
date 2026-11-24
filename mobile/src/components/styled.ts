/**
 * Componentes de fora do React Native com `className` (Tailwind/Uniwind). No celular o Uniwind só aplica classes nos
 * componentes do próprio React Native; os de outras bibliotecas (área segura, animados) precisam do `withUniwind`,
 * senão a classe é ignorada — ex.: `flex-1` some e a tela fica com altura zero (branca). No navegador funciona
 * sem isso, por isso o problema só aparece no Expo Go.
 */
import { Animated } from "react-native";
import { SafeAreaView as SafeAreaViewBase } from "react-native-safe-area-context";
import { withUniwind } from "uniwind";

export const SafeAreaView = withUniwind(SafeAreaViewBase);
export const AnimatedView = withUniwind(Animated.View);
