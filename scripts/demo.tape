Output demo.gif
Set FontSize 15
Set Width 1100
Set Height 640
Set Theme "Catppuccin Mocha"
Set FontFamily "JetBrains Mono"
Set TypingSpeed 20ms
Set Framerate 24
Set Padding 18
Set WindowBar Colorful
Set Shell bash
Hide
Type `export PATH="$BBWARDEN_BIN_DIR:$PATH"`
Enter
Type `cd "$BBWARDEN_DEMO_HOME"`
Enter
Type `export PS1='demo$ '`
Enter
Type `clear`
Enter
Show

Type `bbwarden --version`
Enter
Sleep 0.8s

Type `bbwarden who api --demo`
Enter
Sleep 2.0s

Type `bbwarden direct --demo`
Enter
Sleep 1.8s

Type `bbwarden orphans --demo --idp crowd`
Enter
Sleep 2.5s

Sleep 1.2s
