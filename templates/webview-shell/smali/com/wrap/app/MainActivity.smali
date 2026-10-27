.class public Lcom/wrap/app/MainActivity;
.super Landroid/app/Activity;
.source "MainActivity.java"


# static fields
.field private static final START_URL:Ljava/lang/String; = "https://maps.apple.com/"

.field private static final DESKTOP_UA:Ljava/lang/String; = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"


# instance fields
.field private wv:Landroid/webkit/WebView;


# direct methods
.method public constructor <init>()V
    .registers 1

    invoke-direct {p0}, Landroid/app/Activity;-><init>()V

    return-void
.end method


# virtual methods
.method protected onCreate(Landroid/os/Bundle;)V
    .registers 5
    .param p1, "savedInstanceState"    # Landroid/os/Bundle;

    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    # WebView wv = new WebView(getApplicationContext());
    new-instance v0, Landroid/webkit/WebView;

    invoke-virtual {p0}, Landroid/content/Context;->getApplicationContext()Landroid/content/Context;

    move-result-object v1

    invoke-direct {v0, v1}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    iput-object v0, p0, Lcom/wrap/app/MainActivity;->wv:Landroid/webkit/WebView;

    # WebSettings s = wv.getSettings();
    invoke-virtual {v0}, Landroid/webkit/WebView;->getSettings()Landroid/webkit/WebSettings;

    move-result-object v1

    # s.setJavaScriptEnabled(true)
    const/4 v2, 0x1

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setJavaScriptEnabled(Z)V

    # s.setDomStorageEnabled(true)
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setDomStorageEnabled(Z)V

    # s.setDatabaseEnabled(true)
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setDatabaseEnabled(Z)V

    # s.setMediaPlaybackRequiresUserGesture(false)
    const/4 v2, 0x0

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setMediaPlaybackRequiresUserGesture(Z)V

    # s.setSupportZoom(true)
    const/4 v2, 0x1

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setSupportZoom(Z)V

    # s.setBuiltInZoomControls(true)
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setBuiltInZoomControls(Z)V

    # s.setDisplayZoomControls(false)
    const/4 v2, 0x0

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setDisplayZoomControls(Z)V

    # s.setUserAgentString(DESKTOP_UA)
    sget-object v2, Lcom/wrap/app/MainActivity;->DESKTOP_UA:Ljava/lang/String;

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setUserAgentString(Ljava/lang/String;)V

    # wv.setWebViewClient(new WebViewClient())  -> keep nav in-app
    new-instance v1, Landroid/webkit/WebViewClient;

    invoke-direct {v1}, Landroid/webkit/WebViewClient;-><init>()V

    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->setWebViewClient(Landroid/webkit/WebViewClient;)V

    # wv.loadUrl(START_URL)
    sget-object v1, Lcom/wrap/app/MainActivity;->START_URL:Ljava/lang/String;

    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    # setContentView(wv)
    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V

    return-void
.end method

.method public onBackPressed()V
    .registers 3

    iget-object v0, p0, Lcom/wrap/app/MainActivity;->wv:Landroid/webkit/WebView;

    if-eqz v0, :cond_super

    invoke-virtual {v0}, Landroid/webkit/WebView;->canGoBack()Z

    move-result v1

    if-eqz v1, :cond_back

    invoke-virtual {v0}, Landroid/webkit/WebView;->goBack()V

    return-void

    :cond_back
    invoke-super {p0}, Landroid/app/Activity;->onBackPressed()V

    return-void

    :cond_super
    invoke-super {p0}, Landroid/app/Activity;->onBackPressed()V

    return-void
.end method
