# 明日方舟干员培养材料查询

一个纯静态的小工具，用于查询干员精英化、技能专精和模组升级所需的普通材料，并可将需求展开到紫色或蓝色材料。

## 本地预览

```bash
python3 -m http.server 4173 --directory dist
```

然后访问 <http://127.0.0.1:4173/>。

## 数据维护

- 网站发布：推送到 `main` 后由 GitHub Actions 自动部署 GitHub Pages。
- 数据更新：每周一从 PRTS 检查干员需求、材料列表和合成配方；仅重新解析新增或修订过的页面。
- 更新程序会同步新增干员的分类信息与头像，完成完整性校验后才提交到 `main`，随后自动触发 Pages 部署。
- `Update PRTS data` 和只读的 `Weekly data audit` 均可在 Actions 页面手动运行；前者还可选择完整重建。

本地只读预检（不会覆盖网站数据）：

```bash
python3 -m pip install -r requirements-update.txt
python3 tools/update_prts_data.py --dry-run
```

数据与图片仅用于游戏资料查询；游戏内容版权归其权利人所有。
