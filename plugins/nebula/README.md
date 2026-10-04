# Nebula ChatGPTプラグイン

このフォルダーが本人専用プラグインの配布元。表示名はNebula、作者はTakehiro Fujita、説明は日本語。`assets/nebula-icon.svg`は本体と共通の軽量な星雲の印を使う。

既存プラグイン`plugins_6ab5cfbd21b481919509d03026560f1c`を更新し、`.app.json`にある通常保存先の接続IDとUSER/PRIVATE範囲を維持する。OpenAIの更新APIは既存package名の変更を拒否するため、非表示の`name=dots`だけを保持する。配布物に秘密情報を含めない。登録済みの旧バイナリーを更新APIで削除できない場合は、現行manifestの参照を新アイコンへ切り替え、残存物を利用しない。

検証は配布物の読戻しとChatGPT上の表示を区別する。過去の改名・登録の経緯はGit履歴を参照する。
