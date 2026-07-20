# 应用到 GitHub

当前 ChatGPT GitHub 连接只有读取权限，创建分支和写文件均返回 403，因此本包未直接推送。

在本地执行：

```powershell
git clone https://github.com/zhouwu97/shumozizi.git
cd shumozizi
git checkout -b codex/production-first-workflow-v1

# 将本压缩包内除 APPLY.md 外的文件复制到仓库根目录

git add README.md AGENTS.md docs templates config
git commit -m "feat: establish production-first modeling workflow"
git push -u origin codex/production-first-workflow-v1
```

然后创建 PR，建议标题：

```text
feat: establish production-first modeling and paper workflow
```

不要直接把旧 `shumoziyong` 的 Gate、Profile、Seal 和 Paper Admission 全量复制进来。
