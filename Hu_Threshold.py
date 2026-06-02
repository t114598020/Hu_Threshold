import logging
import os
from typing import Annotated

import vtk

import qt
import ctk
import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

from slicer import vtkMRMLScalarVolumeNode


#
# Hu_Threshold
#


class Hu_Threshold(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Hu_Threshold")
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["John Doe (AnyWare Corp.)"]
        self.parent.helpText = _("""
This module runs DentalSegmentator and performs HU-based layered segmentation on any selected segment.
""")
        self.parent.acknowledgementText = _("""
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")
        slicer.app.connect("startupCompleted()", registerSampleData)


#
# Register sample data sets in Sample Data module
#


def registerSampleData():
    import SampleData
    iconsPath = os.path.join(os.path.dirname(__file__), "Resources/Icons")

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="Hu_Threshold",
        sampleName="Hu_Threshold1",
        thumbnailFileName=os.path.join(iconsPath, "Hu_Threshold1.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        fileNames="Hu_Threshold1.nrrd",
        checksums="SHA256:998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        nodeNames="Hu_Threshold1",
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="Hu_Threshold",
        sampleName="Hu_Threshold2",
        thumbnailFileName=os.path.join(iconsPath, "Hu_Threshold2.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        fileNames="Hu_Threshold2.nrrd",
        checksums="SHA256:1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        nodeNames="Hu_Threshold2",
    )


#
# Hu_ThresholdParameterNode
#


@parameterNodeWrapper
class Hu_ThresholdParameterNode:
    inputVolume: vtkMRMLScalarVolumeNode
    imageThreshold: Annotated[float, WithinRange(-100, 500)] = 100
    invertThreshold: bool = False
    thresholdedVolume: vtkMRMLScalarVolumeNode
    invertedVolume: vtkMRMLScalarVolumeNode


#
# Hu_ThresholdWidget
#


class Hu_ThresholdWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None
        self._segmentationWidget = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        # Create logic class
        self.logic = Hu_ThresholdLogic()

        # ── Step 1：嵌入完整的 DentalSegmentator SegmentationWidget ──
        dentalCollapsible = ctk.ctkCollapsibleButton()
        dentalCollapsible.text = "Step 1: DentalSegmentator"
        self.layout.addWidget(dentalCollapsible)
        dentalLayout = qt.QVBoxLayout(dentalCollapsible)

        from DentalSegmentatorLib import SegmentationWidget
        self._segmentationWidget = SegmentationWidget()
        dentalLayout.addWidget(self._segmentationWidget)

        # ── Step 2：HU 分層區塊 ──────────────────────────────────
        mandibleCollapsible = ctk.ctkCollapsibleButton()
        mandibleCollapsible.text = "Step 2: HU Threshold"
        self.layout.addWidget(mandibleCollapsible)
        mandibleFormLayout = qt.QFormLayout(mandibleCollapsible)

        # 手動選擇 Segmentation node（載入已存場景時使用）
        self._segNodeSelector = slicer.qMRMLNodeComboBox()
        self._segNodeSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
        self._segNodeSelector.setMRMLScene(slicer.mrmlScene)
        self._segNodeSelector.addEnabled = False
        self._segNodeSelector.removeEnabled = False
        self._segNodeSelector.noneEnabled = True
        self._segNodeSelector.showHidden = False
        self._segNodeSelector.setToolTip("選擇要分層的 Segmentation node")
        self._segNodeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onManualSegNodeChanged)
        mandibleFormLayout.addRow("Segmentation:", self._segNodeSelector)

        # 手動選擇 CT Volume node
        self._volumeSelector = slicer.qMRMLNodeComboBox()
        self._volumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self._volumeSelector.setMRMLScene(slicer.mrmlScene)
        self._volumeSelector.addEnabled = False
        self._volumeSelector.removeEnabled = False
        self._volumeSelector.noneEnabled = True
        self._volumeSelector.showHidden = False
        self._volumeSelector.setToolTip("選擇對應的 CT Volume")
        mandibleFormLayout.addRow("CT Volume:", self._volumeSelector)

        # 提示使用者流程
        instructionLabel = qt.QLabel(
            "流程：\n"
            "1. 選擇 Segmentation 和 CT Volume\n"
            "2. 在 Target Segment 選擇要分層的 segment\n"
            "3. 按下下方按鈕\n\n"
            "※ 若載入已存場景，請手動選擇上方的 Segmentation 和 CT Volume"
        )
        instructionLabel.setWordWrap(True)
        mandibleFormLayout.addRow(instructionLabel)

        self._extractButton = qt.QPushButton("Copy Segment && Build HU Layers")
        self._extractButton.toolTip = "複製選擇的 Segment 並依 HU 值建立分層 segments"
        self._extractButton.enabled = False
        mandibleFormLayout.addRow(self._extractButton)

        self._statusLabel = qt.QLabel("請選擇 Segmentation、Target Segment 和 CT Volume")
        self._statusLabel.setWordWrap(True)
        mandibleFormLayout.addRow(self._statusLabel)

        # ── 連結 signals ───────────────────────────────────────────
        # 監聽 segmentationNodeSelector 變化：
        # SegmentationWidget 跑完所有後處理才會 setCurrentNode，這才是真正完成的時機
        self._segmentationWidget.segmentationNodeSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onSegmentationNodeChanged
        )
        self._extractButton.clicked.connect(self.onExtractMandible)

        # 保留 scene close observers
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.layout.addStretch(1)

    def cleanup(self) -> None:
        self.removeObservers()

    def enter(self) -> None:
        pass

    def exit(self) -> None:
        pass

    def onSceneStartClose(self, caller, event) -> None:
        self._extractButton.enabled = False
        self._statusLabel.text = "請先在 Step 1 執行 DentalSegmentator"

    def onSceneEndClose(self, caller, event) -> None:
        pass

    def onSegmentationNodeChanged(self, node):
        """SegmentationWidget 完成所有後處理並設定好 node 後觸發，同步更新 selector 並啟用 Step 2。"""
        if node is None:
            return
        logging.info(f"Segmentation node 已就緒：{node.GetName()}，可以執行 Step 2")
        # 同步更新手動 selector
        self._segNodeSelector.setCurrentNode(node)
        # CT volume 也一起同步
        volumeNode = self._segmentationWidget.getCurrentVolumeNode()
        if volumeNode:
            self._volumeSelector.setCurrentNode(volumeNode)
        self._extractButton.enabled = True
        # self._statusLabel.text = f"DentalSegmentator 完成（{node.GetName()}）！可以點擊下方按鈕擷取 Mandible"

    def onManualSegNodeChanged(self, node):
        """使用者手動選擇 Segmentation node 時，啟用 Step 2 按鈕。"""
        self._extractButton.enabled = (node is not None)
        if node:
            self._statusLabel.text = f"已選擇：{node.GetName()}，請選擇 Target Segment 後按下按鈕"
        else:
            self._statusLabel.text = "請選擇 Segmentation"

    def onExtractMandible(self):
        """複製選擇的 segment 並依 HU 值新增分層 segments。"""
        with slicer.util.tryWithErrorDisplay(_("Failed to build HU layers."), waitCursor=True):
            # 優先從手動 selector 取得 node，其次從 SegmentationWidget
            dentalSegNode = self._segNodeSelector.currentNode()
            if not dentalSegNode:
                dentalSegNode = self._segmentationWidget.getCurrentSegmentationNode()
            if not dentalSegNode:
                slicer.util.errorDisplay("請選擇要分層的 Segmentation node！")
                return

            # 優先從手動 selector 取得 volume，其次從 SegmentationWidget
            volumeNode = self._volumeSelector.currentNode()
            if not volumeNode:
                volumeNode = self._segmentationWidget.getCurrentVolumeNode()
            if not volumeNode:
                slicer.util.errorDisplay("請選擇對應的 CT Volume！")
                return

            newSegNode = self.logic.extractMandible(dentalSegNode, volumeNode)
            if newSegNode:
                layerCount = newSegNode.GetSegmentation().GetNumberOfSegments() - 2  # 扣掉棕色和白色
                self._statusLabel.text = f"完成！棕色＋白色 + {layerCount} 個 HU 分層已建立。"
                slicer.util.infoDisplay(f"完成！棕色＋白色 + {layerCount} 個 HU 分層 segments 已建立。")


#
# Hu_ThresholdLogic
#


class Hu_ThresholdLogic(ScriptedLoadableModuleLogic):

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)

    def getParameterNode(self):
        return Hu_ThresholdParameterNode(super().getParameterNode())

    def process(self,
                inputVolume: vtkMRMLScalarVolumeNode,
                outputVolume: vtkMRMLScalarVolumeNode,
                imageThreshold: float,
                invert: bool = False,
                showResult: bool = True) -> None:
        """原始 threshold 方法保留，避免測試錯誤。"""
        if not inputVolume or not outputVolume:
            raise ValueError("Input or output volume is invalid")

        import time
        startTime = time.time()
        logging.info("Processing started")

        cliParams = {
            "InputVolume": inputVolume.GetID(),
            "OutputVolume": outputVolume.GetID(),
            "ThresholdValue": imageThreshold,
            "ThresholdType": "Above" if invert else "Below",
        }
        cliNode = slicer.cli.run(slicer.modules.thresholdscalarvolume, None, cliParams, wait_for_completion=True, update_display=showResult)
        slicer.mrmlScene.RemoveNode(cliNode)

        stopTime = time.time()
        logging.info(f"Processing completed in {stopTime-startTime:.2f} seconds")

    # HU 分層定義：(名稱, HU下限, HU上限, R, G, B)
    HU_LAYERS = [
        ("0-100",    0,    100,  0.00, 0.00, 0.00),  # 黑色
        ("100-250",  101,  250,  0.50, 0.00, 0.50),  # 紫色
        ("250-400",  251,  400,  0.00, 0.00, 1.00),  # 藍色
        ("400-600",  401,  600,  0.00, 0.80, 0.00),  # 綠色
        ("600-800",  601,  800,  1.00, 0.00, 0.00),  # 紅色
        ("800-1000", 801, 1000,  1.00, 1.00, 0.00),  # 黃色
    ]

    def extractMandible(self, dentalSegNode, volumeNode):
        """
        複製指定 segment 到新 Segmentation node 並設為棕色，然後依 HU 值新增分層 segments。
        :param dentalSegNode: 來源 vtkMRMLSegmentationNode
        :param volumeNode: 原始 CT volume（用於 HU 分層）
        :param selectedSegmentId: 使用者指定的 segment ID
        :return: 新建立的 vtkMRMLSegmentationNode，或 None
        """
        segmentation = dentalSegNode.GetSegmentation()

        # 確認使用者有選擇 segment
        if not selectedSegmentId or not segmentation.GetSegment(selectedSegmentId):
            slicer.util.errorDisplay("請在 Target Segment 選擇要進行 HU 分層的 segment！")
            return None

        mandibleId = selectedSegmentId
        segName = segmentation.GetSegment(mandibleId).GetName()
        logging.info(f"使用指定 segment：{segName}（id={mandibleId}）")

        # ── 建立新的 Segmentation node ──────────────────────────
        newSegNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        newSegNode.SetName("Hu_Threshold")
        newSegNode.CreateDefaultDisplayNodes()
        newSegNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)

        # 把新 node 放到和 CT volume 同一層（Subject Hierarchy）
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeItem = shNode.GetItemByDataNode(volumeNode)
        parentItem = shNode.GetItemParent(volumeItem)
        newSegItem = shNode.GetItemByDataNode(newSegNode)
        shNode.SetItemParent(newSegItem, parentItem)
        logging.info(f"新 Segmentation node 已移至 Subject Hierarchy parent item: {parentItem}")

        # ── 複製選擇的 segment（棕色）─────────────────────────
        newSegNode.GetSegmentation().CopySegmentFromSegmentation(
            dentalSegNode.GetSegmentation(),
            mandibleId
        )
        mandibleCopiedId = newSegNode.GetSegmentation().GetNthSegmentID(0)
        mandibleSegment = newSegNode.GetSegmentation().GetSegment(mandibleCopiedId)
        mandibleSegment.SetName(segName)
        mandibleSegment.SetColor(170/255, 85/255, 0.00)  # 棕色
        logging.info(f"Segment {segName} 已複製並設為棕色")

        # ── 再複製一份（白色）──────────────────────────────────
        newSegNode.GetSegmentation().CopySegmentFromSegmentation(
            dentalSegNode.GetSegmentation(),
            mandibleId
        )
        # 白色的是第二個 segment
        whiteSegId = newSegNode.GetSegmentation().GetNthSegmentID(1)
        whiteSeg = newSegNode.GetSegmentation().GetSegment(whiteSegId)
        whiteSeg.SetName(segName + "_white")
        whiteSeg.SetColor(1.0, 1.0, 1.0)  # 白色
        logging.info(f"Segment {segName}_white 已複製並設為白色")

        # ── 確保有 binary labelmap representation ───────────────
        if not newSegNode.GetSegmentation().ContainsRepresentation(
            slicer.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName()
        ):
            newSegNode.GetSegmentation().CreateRepresentation(
                slicer.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName()
            )

        # ── 取得 segment 的 voxel mask（numpy array）──────────
        import numpy as np
        segArray = slicer.util.arrayFromSegmentBinaryLabelmap(newSegNode, mandibleCopiedId, volumeNode)
        ctArray  = slicer.util.arrayFromVolume(volumeNode)

        logging.info(f"Segment mask shape: {segArray.shape}, CT shape: {ctArray.shape}")

        # ── 依 HU 範圍建立各 segment ────────────────────────────
        for name, huLow, huHigh, r, g, b in self.HU_LAYERS:
            # 在 segment mask 內，找符合 HU 範圍的 voxel
            layerMask = (segArray > 0) & (ctArray >= huLow) & (ctArray <= huHigh)

            if not np.any(layerMask):
                logging.info(f"  {name}: 沒有符合的 voxel，跳過")
                continue

            # 新增 segment
            newSegId = newSegNode.GetSegmentation().AddEmptySegment(name)
            newSeg = newSegNode.GetSegmentation().GetSegment(newSegId)
            newSeg.SetName(name)
            newSeg.SetColor(r, g, b)

            # 將 mask 寫入 segment
            slicer.util.updateSegmentBinaryLabelmapFromArray(
                layerMask.astype(np.uint8), newSegNode, newSegId, volumeNode
            )
            logging.info(f"  {name}: {np.sum(layerMask)} voxels，顏色 ({r:.2f},{g:.2f},{b:.2f})")

        # ── 顯示在畫面上 ────────────────────────────────────────
        newSegNode.GetDisplayNode().SetVisibility(True)

        logging.info("HU 分層完成！")
        return newSegNode


#
# Hu_ThresholdTest
#


class Hu_ThresholdTest(ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_Hu_Threshold1()

    def test_Hu_Threshold1(self):
        self.delayDisplay("Starting the test")

        import SampleData
        registerSampleData()
        inputVolume = SampleData.downloadSample("Hu_Threshold1")
        self.delayDisplay("Loaded test data set")

        inputScalarRange = inputVolume.GetImageData().GetScalarRange()
        self.assertEqual(inputScalarRange[0], 0)
        self.assertEqual(inputScalarRange[1], 695)

        outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        threshold = 100

        logic = Hu_ThresholdLogic()

        logic.process(inputVolume, outputVolume, threshold, True)
        outputScalarRange = outputVolume.GetImageData().GetScalarRange()
        self.assertEqual(outputScalarRange[0], inputScalarRange[0])
        self.assertEqual(outputScalarRange[1], threshold)

        logic.process(inputVolume, outputVolume, threshold, False)
        outputScalarRange = outputVolume.GetImageData().GetScalarRange()
        self.assertEqual(outputScalarRange[0], inputScalarRange[0])
        self.assertEqual(outputScalarRange[1], inputScalarRange[1])

        self.delayDisplay("Test passed")